"""Availability calculation and immutable scheduling snapshots. No calendar event text."""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import select, update

from .calendar_models import CalendarConnection
from .calendar_provider import CalendarProvider, CalendarUnavailable, configured
from .models import Customer, RateBucket, now

CALENDAR_FIELDS = ('calendar_check', 'duration_minutes', 'calendar_generation', 'proposed_slots')


def utc(value):
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def lock_customer(db, customer_id):
    db.execute(update(Customer).where(Customer.id == customer_id).values(id=Customer.id))
    db.expire_all()


def consume_rate(db, customer_id, action, limit):
    bucket = int(now().timestamp() // 3600)
    row = db.get(RateBucket, (customer_id, action, bucket))
    if row and row.count >= limit:
        raise HTTPException(429, 'Too many calendar attempts. Please try later.')
    if row:
        row.count += 1
    else:
        db.add(RateBucket(customer_id=customer_id, action=action, hour_bucket=bucket, count=1))


def zone(value):
    try:
        return ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError, TypeError):
        raise ValueError('Choose a valid IANA time zone.') from None


class CalendarChecked(BaseModel):
    calendar_check: bool = False
    duration_minutes: int = Field(default=60, ge=30, le=480)
    calendar_generation: int | None = Field(default=None, ge=0)


class AvailabilityWrite(BaseModel):
    model_config = ConfigDict(extra='forbid')
    time_min: datetime
    time_max: datetime
    duration_minutes: int = Field(default=60, ge=30, le=480)
    time_zone: str = Field(max_length=100)
    day_start_hour: int = Field(default=9, ge=0, le=23)
    day_end_hour: int = Field(default=17, ge=1, le=24)

    @field_validator('time_min', 'time_max', mode='before')
    @classmethod
    def string_dates(cls, value):
        if not isinstance(value, str):
            raise ValueError('Use an ISO timestamp.')
        return value

    @field_validator('time_min', 'time_max')
    @classmethod
    def aware_dates(cls, value):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError('Use an offset-aware timestamp.')
        try:
            return value.astimezone(timezone.utc)
        except OverflowError:
            raise ValueError('Choose a valid appointment date.') from None

    @field_validator('time_zone')
    @classmethod
    def time_zone_valid(cls, value):
        zone(value)
        return value

    @model_validator(mode='after')
    def valid_window(self):
        current = now()
        if not current + timedelta(hours=1) <= self.time_min < self.time_max <= current + timedelta(days=90):
            raise ValueError('Choose a future window within 90 days.')
        if self.time_max - self.time_min > timedelta(days=14) or self.day_end_hour <= self.day_start_hour:
            raise ValueError('Choose a valid window up to 14 days.')
        return self


def binding(db, customer_id, settings, *, selected=True):
    customer = db.get(Customer, customer_id)
    if not configured(settings) or not customer or customer.demo:
        raise HTTPException(503, 'Google Calendar is unavailable.')
    row = db.get(CalendarConnection, customer_id)
    if not row or row.status != 'connected' or not row.nango_connection_id:
        raise HTTPException(409, 'Connect Google Calendar first.')
    if row.integration_id != settings.nango_calendar_integration_id or row.environment != settings.nango_environment:
        raise HTTPException(409, 'Reconnect Google Calendar.')
    if selected and not 1 <= len(row.selected_calendar_ids) <= 10:
        raise HTTPException(409, 'Choose calendars to check.')
    return row


def snapshot(row):
    return {'calendar_check': True, 'calendar_generation': row.generation,
            'calendar_selected_ids': list(row.selected_calendar_ids), 'calendar_time_zone': row.time_zone,
            'calendar_sync_enabled': row.sync_confirmed}


def unchanged(db, customer_id, settings, generation, connection_id):
    db.expire_all()
    row = binding(db, customer_id, settings, selected=False)
    if row.generation != generation or row.nango_connection_id != connection_id:
        raise HTTPException(409, 'Calendar preferences changed. Try again.')
    return row


def overlaps(start, end, intervals):
    return any(start < b and end > a for a, b in intervals)


def candidates(start, end, duration, time_zone, first_hour, last_hour, intervals):
    tz = zone(time_zone)
    date = start.astimezone(tz).date()
    last_date = end.astimezone(tz).date()
    results = []
    while date <= last_date:
        if date.weekday() < 5:
            for minute in range(first_hour * 60, last_hour * 60, 30):
                wall = datetime.combine(date, datetime.min.time()) + timedelta(minutes=minute)
                local = wall.replace(tzinfo=tz, fold=0)
                a = local.astimezone(timezone.utc)
                # Reject DST gaps and ambiguous wall times, rather than silently shifting an offer.
                if a.astimezone(tz).replace(tzinfo=None) != wall or local.utcoffset() != wall.replace(tzinfo=tz, fold=1).utcoffset():
                    continue
                b = a + timedelta(minutes=duration)
                finish = b.astimezone(tz)
                boundary = datetime.combine(date, datetime.min.time()) + timedelta(hours=last_hour)
                if a < start or b > end or finish.replace(tzinfo=None) > boundary or overlaps(a, b, intervals):
                    continue
                results.append({'start': a.isoformat(), 'end': b.isoformat()})
                if len(results) == 12:
                    return results
        date += timedelta(days=1)
    return results


def legacy_payload(body, *, mode='json', directory=False):
    data = body.model_dump(mode=mode)
    fields = CALENDAR_FIELDS if directory else CALENDAR_FIELDS[:-1]
    for key in fields:
        if key not in body.model_fields_set:
            data.pop(key, None)
    return data


def check_slots(db, settings, transport, customer_id, slots, duration, generation, *, frozen=None, exclude=None):
    """Caller owns the customer lock through the admission transaction and bounded read."""
    try:
        row = binding(db, customer_id, settings)
    except HTTPException as exc:
        if exc.status_code == 409:
            raise HTTPException(422, 'Calendar access changed. Choose new appointment times.') from None
        raise
    if generation is None or generation != row.generation or frozen and (
            frozen.calendar_selected_ids != row.selected_calendar_ids or frozen.calendar_time_zone != row.time_zone):
        raise HTTPException(422, 'Calendar preferences changed. Choose new appointment times.')
    current = now()
    starts = [utc(v) for v in slots]
    if not 1 <= len(starts) <= 3 or any(v is None or v < current + timedelta(hours=1) or
            v > current + timedelta(days=90) - timedelta(minutes=duration) for v in starts):
        raise HTTPException(422, 'Choose one to three future appointment times.')
    if max(starts) + timedelta(minutes=duration) - min(starts) > timedelta(days=14):
        raise HTTPException(422, 'Choose appointment times within one 14-day window.')
    try:
        intervals = CalendarProvider(settings, transport).freebusy(row.nango_connection_id, row.selected_calendar_ids,
                    min(starts), max(starts) + timedelta(minutes=duration))
    except CalendarUnavailable as exc:
        provider_failure(db, customer_id, row.generation, row.nango_connection_id, exc, admission=True)
    intervals += booked_intervals(db, customer_id, min(starts), max(starts) + timedelta(minutes=duration), exclude=exclude)
    if any(overlaps(v, v + timedelta(minutes=duration), intervals) for v in starts):
        raise HTTPException(422, 'A proposed time is now busy. Choose new appointment times.')
    return snapshot(row)


def sync_view(source):
    return {key: getattr(source, key) for key in ('calendar_check', 'duration_minutes', 'calendar_generation',
            'calendar_time_zone', 'calendar_sync_status', 'calendar_sync_message')}


def preferred_times(slots, duration, time_zone):
    tz = zone(time_zone)
    return f'{duration} min; ' + '; '.join(v.astimezone(tz).strftime('%b %d %Y %I:%M %p %Z') for v in slots)


def booked_intervals(db, customer_id, start, end, *, exclude=None):
    """Confirmed app bookings block offers even when their Google copy is unselected."""
    from .models import ServiceRequest
    from .shop_models import ShopOutreach
    intervals = []
    for kind, model, state, field in (('request', ServiceRequest, 'scheduled', 'scheduled_at'),
                                       ('outreach', ShopOutreach, 'confirmed', 'confirmed_slot')):
        rows = db.scalars(select(model).where(model.customer_id == customer_id, model.status == state).limit(1001)).all()
        if len(rows) > 1000:
            raise HTTPException(503, 'Appointment availability could not be verified completely.')
        for row in rows:
            if exclude == (kind, row.id):
                continue
            value = getattr(row, field)
            if value is None:
                continue
            try:
                a = utc(datetime.fromisoformat(value)) if isinstance(value, str) else utc(value)
                b = a + timedelta(minutes=row.duration_minutes or 60)
            except (ValueError, TypeError):
                raise HTTPException(503, 'Appointment availability could not be verified completely.') from None
            if a < end and b > start:
                intervals.append((a, b))
    return intervals


def provider_failure(db, customer_id, generation, connection_id, exc, *, admission=False):
    if exc.status in (401, 403):
        lock_customer(db, customer_id)
        row = db.get(CalendarConnection, customer_id)
        if row and row.generation == generation and row.nango_connection_id == connection_id and row.status == 'connected':
            row.status = 'reconnect_required'
            row.generation += 1
            db.commit()
        raise HTTPException(422 if admission else 409, 'Reconnect Google Calendar before checking appointment availability.') from None
    raise HTTPException(503, 'Calendar availability could not be verified. Try again.') from None
