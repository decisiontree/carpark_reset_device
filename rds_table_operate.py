import psycopg2
from config import config

 
def execute(conn, cur, commands):
    try:
        # read the connection parameters
#         params = config()
#         conn = psycopg2.connect(**params)
#         cur = conn.cursor()
#         print(conn) #add conn 1204,1106
        # create table one by one
        for command in commands:
            print(command)
            cur.execute(command)
            #conn.commit() #added 1204,1105
        # close communication with the PostgreSQL database server
        cur.close()
        conn.commit() #commented 1204,1106
    except (Exception, psycopg2.DatabaseError) as error:
        print(error)
    finally:
        if conn is not None:
            conn.close()

def execute_only(conn, cur, commands):
    try:
        for command in commands:
            print(command)
            cur.execute(command)
        conn.commit() 
    except (Exception, psycopg2.DatabaseError) as error:
        print(error)
           
if __name__ == '__main__':
    execute()

