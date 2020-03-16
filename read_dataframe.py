import pandas as pd
import psycopg2
from config import config


def connect_aws(sectionName):
    params = config(sectionName)
    conn = psycopg2.connect(**params)
    cur = conn.cursor()
    return cur, conn


def exec(connection, cursor, query):
    #connection = sql_connect.exec()
    #cursor = connection.cursor()
    cursor.execute( query )
    names = [ x[0] for x in cursor.description]
    rows = cursor.fetchall()
    return pd.DataFrame( [tuple(row) for row in rows], columns=names)


if __name__ == "__main__":
    cur, conn = connect_aws('postgresqldb1')
    print("hello world")
    sql_code = "select * from public.smart_parking limit 10"
    df = exec(conn, cur , sql_code)
    print(df)

