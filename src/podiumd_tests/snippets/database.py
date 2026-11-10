"""The database a Django app uses: vendor, name and installed extensions (e.g. postgis). Params: none."""


def run(_params):
    from django.db import connection

    with connection.cursor() as cursor:
        cursor.execute("SELECT extname FROM pg_extension")
        extensions = sorted(row[0] for row in cursor.fetchall())
    return {"vendor": connection.vendor, "name": connection.settings_dict["NAME"], "extensions": extensions}
