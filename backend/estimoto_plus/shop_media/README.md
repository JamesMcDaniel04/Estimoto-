# Reviewed shop artwork

These thumbnails identify the listed businesses. Original ownership stays with
the credited publisher; a public listing does not imply participation in Estimoto.

Each independent business is bound to its exact OSM source ID, name and address.
The catalog includes the official source page, identity evidence and PNG digest.
Renamed or moved public listings cannot inherit the old image. A reviewed chain
alias also requires a matching official website domain before reusing artwork.

To extend coverage, review a shop's official website and logo (or its own shop
photo), inspect the image, then use `scripts/import_reviewed_shop_artwork.py` with
the reviewed manifest and local raster files. Preserve existing reviewed entries
when regenerating the catalog. No image search result alone establishes identity.

The runtime serves only bounded packaged PNG files, never an arbitrary URL or
private customer upload. Customer identity and tokens are not sent with images.
Missing images stay unavailable; shop initials or generic category icons are not
counted as verified logos.

The separate `businesses` section records official website/contact evidence,
review date, services and exact source coordinates. Discovery admits only those
reviewed independent shops (plus owner-published participating providers), with
30 results total including alternatives. Business reviews expire after 90 days;
changed names, addresses or map pins require renewed verification. Website and
phone enrich cached map data without changing ownership or provider handoffs.
Logos alone never qualify a shop. Google ratings are not inferred from other
review sources; profiles link to Google Maps for current reviews.
