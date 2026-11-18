# Offline branch device (PWA)

Use one designated browser/device at each branch while offline. This adds no paid
service and requires no database migration. Use HTTPS (localhost also works for
development); opening index.html as a file does not enable offline operation.

## Before an outage

1. Open the app online and sign in. Existing sessions created before this release
   need one sign out/sign in so the device knows the original eight-hour expiry.
2. Open **Device & sync**, select the branch, and click **Prepare / update device**.
   A Salesperson's branch is selected automatically and cannot be changed.
3. Wait for **Device prepared**. This downloads the catalogue, that branch's stock
   and customer contacts. Refresh it before each shift, after syncing old sales.
4. Choose **Install app** when offered by Chrome/Edge, or use the browser's install
   menu. On iPhone/iPad use Safari's Add to Home Screen. Installation is optional:
   the same prepared browser can work offline without a separate app window.
5. Keep the device locked when unattended. Do not use private browsing, clear site
   data, uninstall the browser, or switch browsers with unsynced sales.

## During an outage

The connection banner shows **Offline** and the number of sales awaiting sync.
Inventory, product lookup and downloaded customer contacts remain available for
this branch. Stock shown is the downloaded balance minus device sales not yet
accounted for by a fresh server stock download. It is an estimate, not live stock.

Use **Sales** as usual, including search suggestions, approved discounts and Cash
or POS terminal. POS is a payment label: the terminal itself must confirm payment;
this app cannot authorize a bank card offline. Credit sales need an active customer
already downloaded for this branch. Creating a new customer, recording repayments,
receiving stock, transfers, product/account changes, reports and daily counts need
internet. Earlier history is not downloaded; local device receipts are available.

A complete sale is saved to IndexedDB before its basket clears. Its provisional
receipt begins **OFF-** and shows **AWAITING SYNC**, the device capture time, items,
payment method and total. Print/save it for the customer. Do not enter it again
online as a new sale. If storage fails, the basket remains; free space without
clearing this app's site data and try again. Unsaved baskets are not preserved on
page reload, so complete the basket before closing or reloading the app.

The existing sign-in lasts eight hours from online login; offline refresh does not
extend it. Reopening the prepared browser during that period restores the same
account. Once it expires, reconnect and sign in as the original staff member.
Queued sales survive expiry and sign-out. Other accounts cannot view or upload
those receipts. Resolve the original account's queue before preparing another
account on this device. Revocations cannot be learned while disconnected; the
server rechecks active account, permissions and branch on every upload.

## When the connection returns

Keep the app open, or reopen it. It checks on reconnection, returning to the app,
and every 30 seconds while saved sales remain. **Sync now** also checks manually.
Uploading while the app is closed is not guaranteed. Wait for **0 sale(s) awaiting
sync** before submitting the daily count. Sales are uploaded in order. A confirmed
sale gets the normal server receipt; recent confirmed device receipts remain in
Device & sync (up to 200 after stock refresh). Server history remains authoritative.

Each sale keeps a fixed UUID and unchanged request. If the server saved it but the
response was lost, retrying that UUID returns the existing result instead of selling
the stock twice. Server stock deduction, sale/items and stock movements remain in
the existing PostgreSQL transaction: either all commit or none do.

**Needs review** stops later uploads. It can mean insufficient server stock, a
changed price/discount, an inactive customer/product, or changed permissions.
The original sale, error and stock reservation remain on this device. Ask a Manager
to investigate and correct the actual underlying issue. Then choose **Retry after
review**, which sends the same sale/reference. There is deliberately no automatic
deletion, price adjustment or replacement sale. For a genuine sale that cannot be
accepted under current rules, export the device sales and have the owner reconcile
it before changing any business records. The export is a recovery/audit copy, not
an automatic import; it includes customer/receipt data but no sign-in token.

## Dates and reports

Provisional receipts use the device's capture time, displayed in Lagos time. The
full UUID and capture timestamp are preserved in the server sale's notes. Keep the
device clock correct. The existing server created_at and financial-report business
date remain the time the upload is posted. A sale captured before midnight and
uploaded after midnight therefore posts to the later day's report. Sync before
closing the day's reconciliation. This version does not backdate financial reports.

## How the code fits together

- manifest.webmanifest and the FA icons make the app installable.
- sw.js caches only the public app shell. Authenticated APIs never enter Cache Storage.
  When changing a shell asset, bump VERSION in sw.js to distribute the new release.
  An update activates through **Reload updated app**, after finishing the basket.
- offline-store.js owns IndexedDB transactions. It saves complete sales atomically,
  checks stock reservations across tabs, and preserves unsynced records. A stock
  snapshot and release of confirmed reservations commit together to survive reloads.
- offline.js prepares branch data, enforces the cached limits, shows receipts/queue,
  and serializes uploads across tabs with Web Locks. It reuses POST /checkouts and
  the existing Idempotency-Key; there is no second sales backend or new schema.
- app.js routes prepared-branch checkouts through that queue and uses downloaded
  data when offline. Other branches retain the existing online checkout flow.

Private snapshots/queues live in this browser's IndexedDB. A prepared device also
stores its opaque bearer token, cached account and original expiry there so it can
reopen offline; passwords are never stored. Logout removes that offline identity,
not unsynced sales. Normal unprepared login stays tab-scoped. Browser storage is
not a server backup and is not encrypted by this app: use a trusted device and OS
lock. Persistent storage is requested, but the browser may refuse it; clearing or
losing the device can still lose unsynced sales. Export when recovery is needed.

## Safe checks

Run powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass -File
backend/tests/run_ui_checks.ps1 -Suite offline. This uses the disposable PostgreSQL
cluster on port 55439 and API port 58541, not local business or hosted data. It
checks real browser disconnection, offline reload, Cash/POS/credit saves, durable
stock reservations, failed browser storage, lost-response replay, conflict review,
expired sign-in recovery and account isolation. The smoke and layout suites still
check normal online workflows and screen sizes.
