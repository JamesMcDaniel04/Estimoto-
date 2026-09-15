"""Delete the signed-in customer's account and everything it owns."""
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from .account import delete_auth_identity, delete_customer_data
from .auth import current_customer, db_session
from .calendar_scheduling import lock_customer
from .models import Customer

router = APIRouter(tags=['customer account'])


@router.delete('/v1/account')
def delete_account(request: Request, c: Customer = Depends(current_customer), db: Session = Depends(db_session)):
    if c.demo:
        raise HTTPException(403, 'Sample accounts cannot be deleted. Leave the demo instead.')
    settings, customer_id = request.app.state.settings, c.id
    lock_customer(db, customer_id)
    from .customer_routes import consume_rate
    consume_rate(db, customer_id, 'account_delete', 3)
    db.commit()
    counts = delete_customer_data(db, settings, customer_id)
    identity = delete_auth_identity(settings, customer_id, getattr(request.app.state, 'auth_admin_transport', None))
    cache = getattr(request.app.state, 'auth_cache', None)
    if cache is not None:
        cache.clear()
    return {'deleted': True, 'identity_deleted': identity, 'removed': counts}
