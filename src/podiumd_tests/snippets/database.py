"""The database a Django app uses: vendor, name and installed extensions (e.g. postgis). Params: none."""


def run(params):
    from django.db import connection

    with connection.cursor() as cursor:
        cursor.execute("SELECT extname FROM pg_extension")
        extensions = sorted(row[0] for row in cursor.fetchall())
    del params  # run() takes params like every snippet; this one has none
    return {"vendor": connection.vendor, "name": connection.settings_dict["NAME"], "extensions": extensions}
