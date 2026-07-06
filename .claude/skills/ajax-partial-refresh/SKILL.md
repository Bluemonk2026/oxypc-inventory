---
name: ajax-partial-refresh
description: Use when a user asks that "the whole page should not reload, only the table/section should update" after a form submit or bulk action (e.g. assigning dealers, bulk status changes). Converts a full-page-redirect POST flow into an AJAX partial DOM swap without breaking existing DataTables/checkbox JS.
---

# AJAX Partial Table Refresh (OxyPC Inventory)

## When to use

A page has a form (often inside a modal) that POSTs, and today the whole page
reloads via `RedirectResponse` afterward. The user wants only a table/summary
region to update in place — established for Assign Dealer Leads' bulk-assign
flow.

## Backend: dual response, same endpoint

Keep the existing redirect for non-JS / direct form posts, but detect AJAX via
the `X-Requested-With` header and return JSON instead:

```python
await db.commit()
if request.headers.get("x-requested-with") == "XMLHttpRequest":
    from fastapi.responses import JSONResponse
    return JSONResponse({"success": True, "count": len(dealers), "assigned_to": assigned_to})
return RedirectResponse(url=..., status_code=303)
```

This is backward compatible — no existing caller breaks.

## Frontend: fetch + DOMParser swap, not innerHTML from a JSON blob

1. Wrap the region(s) that need to refresh in stable IDs, e.g.
   `<div id="assignDealerTableWrap">` and `<div id="assignDealerSummaryCards">`.
2. On form submit, intercept with `fetch()` + `FormData`:
   ```js
   assignForm.addEventListener('submit', async function(e) {
     if (!window.fetch) return; // fall back to normal submit
     e.preventDefault();
     const res = await fetch(assignForm.action, {
       method: 'POST', body: new FormData(assignForm),
       headers: { 'X-Requested-With': 'XMLHttpRequest' },
     });
     if (res.ok) {
       bootstrap.Modal.getInstance(modalEl)?.hide();
       await refreshDealerLeadsTable();
     }
   });
   ```
3. `refreshDealerLeadsTable()` re-fetches the **current page URL** (not the
   POST endpoint) with the same AJAX header, parses the HTML response with
   `DOMParser`, and swaps just the wrapped regions' `innerHTML`:
   ```js
   async function refreshDealerLeadsTable() {
     const res = await fetch(window.location.href, { headers: { 'X-Requested-With': 'XMLHttpRequest' } });
     const doc = new DOMParser().parseFromString(await res.text(), 'text/html');
     document.getElementById('assignDealerTableWrap').innerHTML =
       doc.getElementById('assignDealerTableWrap').innerHTML;
     document.getElementById('assignDealerSummaryCards').innerHTML =
       doc.getElementById('assignDealerSummaryCards').innerHTML;
     initDealerLeadsTable();   // destroy+reinit DataTable on the new DOM
     rebindRowHandlers();      // re-attach per-row click handlers lost in the swap
     updateSelUI();
   }
   ```
   Note the GET route must also honor `X-Requested-With` and simply render its
   normal full template — the JSON branch is only for the POST endpoint. The
   DOMParser then extracts just the fragments needed from the full HTML.

## Do not forget to rebind

Any `.btnAssignOne` / `.btnDeleteOne` / checkbox listeners that were bound
once at page load must be re-bound after each swap — the new DOM nodes have
no listeners. Extract the binding logic into a named function
(`rebindRowHandlers()`) called both at initial load and after every refresh,
rather than duplicating the binding code.

## Verify

Load the page, submit the AJAX form, and confirm via `preview_network` /
`preview_console_logs` that: (a) no full navigation occurred, (b) the table
row disappears/updates without a flash, (c) row-level buttons (assign/delete)
still work on rows that existed before AND after the refresh.
