"""NetSuite general ledger load for the Caldergate Data Hub.

This script is the first step of the Daily Load. The scheduler starts it at
05:00 UK time, before the Anaplan process of the same name runs. It pulls the
general ledger from a NetSuite saved search, writes one CSV file, and uploads
that file to the Data Hub, where the action "Import GL from NetSuite" loads it
into the module DAT01 GL Transactions.

The load is daily, although the planning model takes actuals monthly, because
the hub's data checks compare the ledger with sales orders every morning and
Group Reporting want to see a posting problem the day after it happens, not at
the close.

Each row of the file is one cost centre, account and period, with three values:
Amount, Journal Count and Source System. Source System is loaded as text on
every row because the ledger receives journals from NetSuite itself and from
the warehouse billing interface, and Group Reporting asked to see which system
a balance came from when the hub's data check reports a difference.

Credentials are read from the environment. Nothing secret is kept in this file.
"""

import csv
import os
from datetime import date

SAVED_SEARCH = "customsearch_cdg_gl_by_cc_account_period"
UPLOAD_FILE = "gl_transactions.csv"
COLUMNS = ["Cost Centre", "Account", "Period", "Amount", "Journal Count", "Source System"]
SOURCE_SYSTEMS = {"NS": "NetSuite", "WBI": "Warehouse billing interface"}


def open_periods(today):
    """Return the periods to reload: the current month and the month before.

    Two months are reloaded every day because the ledger for the prior month
    stays open for late journals until working day 3, and a full reload of
    both is simpler and safer than working out what changed.
    """
    this_month = date(today.year, today.month, 1)
    if this_month.month == 1:
        last_month = date(this_month.year - 1, 12, 1)
    else:
        last_month = date(this_month.year, this_month.month - 1, 1)
    return [last_month.strftime("%b %y"), this_month.strftime("%b %y")]


def fetch_ledger(client, periods):
    """Run the saved search for the given periods and return its rows.

    The saved search groups the ledger by cost centre, account and period.
    It returns the summed amount in local currency with the ledger's own sign,
    the number of journals behind it, and the code of the system that posted
    the largest journal.
    """
    return client.run_saved_search(SAVED_SEARCH, filters={"period": periods})


def to_row(record):
    """Turn one saved search record into one row of the upload file.

    Cost centres and accounts are sent as codes, never names, because the hub
    maps on code. An unknown source code is passed through unchanged so that
    it shows up in the hub and is not silently relabelled.
    """
    source = SOURCE_SYSTEMS.get(record["source_code"], record["source_code"])
    return [
        record["cost_centre_code"],
        record["account_code"],
        record["period"],
        f"{record['amount']:.2f}",
        record["journal_count"],
        source,
    ]


def write_file(rows, path):
    """Write the upload file, with a header row, replacing any earlier file."""
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(COLUMNS)
        writer.writerows(rows)
    return len(rows)


def main(netsuite_client, anaplan_client):
    """Fetch the ledger, write the file and upload it to the Data Hub.

    The script only uploads the file. It does not run the import. The Anaplan
    process Daily Load runs "Import GL from NetSuite" and then the Salesforce
    imports, so that a failed upload leaves yesterday's file in place and the
    process still completes with yesterday's ledger.
    """
    periods = open_periods(date.today())
    rows = [to_row(record) for record in fetch_ledger(netsuite_client, periods)]
    count = write_file(rows, UPLOAD_FILE)
    anaplan_client.upload_file(
        workspace=os.environ["CDG_HUB_WORKSPACE_ID"],
        model=os.environ["CDG_HUB_MODEL_ID"],
        name=UPLOAD_FILE,
        path=UPLOAD_FILE,
    )
    print(f"Uploaded {count} ledger rows for {', '.join(periods)}")


if __name__ == "__main__":
    raise SystemExit("Run from the scheduler wrapper, which supplies the two clients.")
