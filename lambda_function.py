#We treat each device as slow change dimension (warehouse table) and store the "current" 

import json
import pandas as pd
import time
from datetime import datetime, timedelta, timezone
import psycopg2

import boto3
from boto3.dynamodb.conditions import Key, Attr
from boto3 import resource

import confglobal
import rds_table_operate
from config import config
import read_dataframe




def connect_aws(sectionName):
    params = config(sectionName)
    conn = psycopg2.connect(**params)
    cur = conn.cursor()
    return cur, conn

cur, conn = connect_aws('postgresqlprod')

#When join delta with status table, they can get locked.
#have avoided join in the sql statement
def reset_dev_status(df_xyz_last_filter, dev_reset_list_str):

    sqlUpdateStatus = (
        f"""
        update public.dev_status as status 
        set current_status = 0
        where status.dev_id in {dev_reset_list_str}
        and status.current_status = 1""", )

    sqlInsertLatest = ['''insert into public.dev_status (dev_id, time, x, y, z, current_status) values \
        ('{}','{}','{}','{}','{}','{}')'''.format(*[row['dev_id'], row['time'], row['x'], row['y'], row['z'], 1])
                       for index, row in df_xyz_last_filter.iterrows()]

    sqlReportLatest = ['''insert into public.dev_report (dev_id, status_time, x, y, z, availability) values \
        ('{}','{}','{}','{}','{}','{}')'''.format(*[row['dev_id'], row['time'], row['x'], row['y'], row['z'], 1])
                       for index, row in df_xyz_last_filter.iterrows()]

    #rds_table_operate.execute_only(conn, cur, sqlUpdateStatus)    
    #this is the step hangs(lock) the process if I use join

    sqlCommandList= tuple([sqlUpdateStatus[0], *sqlInsertLatest, *sqlReportLatest])

    rds_table_operate.execute_only(conn, cur, sqlCommandList)
    #cur.close()
    #conn.close()


def filter_device_list(event, df):
    dev_reset_list = []
    if (len(event['dev_id'])==1) & (event['dev_id'][0]=='all'):
        dev_reset_list = df['dev_id'].unique()
    else:
        dev_reset_list = event['dev_id']  #can be a list of devices instead just one
    df_xyz_last_filter = df[df['dev_id'].isin(dev_reset_list)].copy()
    return df_xyz_last_filter, list(df_xyz_last_filter.dev_id.unique())


def get_window_data(dict_time):
    #select current_date
    sqlcmd = f"""
            select dev_id,x,y,z,time,
                    date(to_timestamp(time, 'YYYY-MM-DD hh24:mi:ss')) cur_date
            from public.smart_parking
            where to_timestamp(time, 'YYYY-MM-DD hh24:mi:ss') between 
            '{dict_time['utcWindowStartStr']}' and '{dict_time['utcNowStr']}' """  

    df = read_dataframe.exec(conn, cur, sqlcmd)
    df['time_obj'] = pd.to_datetime(df['time'], utc=True)

    #filter noise; as Trung suggested signal with read 0,0,0 are noise
    df = df.loc[ df['x']+df['y']+df['z'] != 0]
    
    
    #get the last record for each deviced, in the last N minutes
    df_xyz_last = df.sort_values(["time"], ascending = True) \
                .groupby(['dev_id'])[['x', 'y', 'z', 'time', 'time_obj']] \
                .last() \
                .reset_index()            
    return df_xyz_last


def define_window_timestamp(WINDOWLEN):    
    time_dict=dict()
    #time window FROM to TO
    time_dict['utcNow'] = datetime.now(timezone.utc)
    time_dict['utcWindowStart'] = time_dict['utcNow'] - timedelta(seconds=WINDOWLEN)
    time_dict['utcNowStr'] = time_dict['utcNow'].strftime("%Y-%m-%dT%H:%M:%S").split('.')[0]
    time_dict['utcWindowStartStr'] = time_dict['utcWindowStart'].strftime("%Y-%m-%dT%H:%M:%S").split('.')[0]
    return time_dict


def lambda_handler(event, context):
    #record program start time ;
    #not all values in this dictionary is used
    dict_time = define_window_timestamp(confglobal.WINDOWLEN)
    df_xyz_last = get_window_data(dict_time)
    df_xyz_last_filter, dev_reset_list = filter_device_list(event, df_xyz_last)   
    dev_reset_list_str = '(\'' + '\',\''.join(dev_reset_list) + '\')'
    reset_dev_status(df_xyz_last_filter, dev_reset_list_str)


if __name__ == "__main__":
    test_json = {
        "dev_id": ["node0003"],
    #    "dev_id": ["node0001","node0002","node0003","node0004","node0005"\
    #              ,"node0006","node0007","node0008","node0009","node0010"],
        "key3": "999"
    }
    response = lambda_handler(test_json, None)

