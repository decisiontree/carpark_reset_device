#can we treat each device as slow change dimension (warehouse table) and store the "current" empty space magnetic field?
#It can be saved as a x, y, z timestamp , status relational table.
#when a car drive in, we 

import json
import pandas as pd
import time
import psycopg2
from datetime import datetime, timedelta, timezone 

import boto3
from boto3.dynamodb.conditions import Key, Attr
from boto3 import resource

import confglobal
from config import config
from config import config_dynamodb
import rds_table_operate



def connect_aws():
    #conn_string = "host='database-1.cog2qgcanxfu.ap-southeast-2.rds.amazonaws.com' port=5432 dbname='ttn' user='postgres' password='qweasdzxc'"
    #conn = psycopg2.connect(conn_string)
    #cur = conn.cursor()
    params = config()
    conn = psycopg2.connect(**params)
    cur = conn.cursor()
    return cur, conn


#load delta table(latest xyz) into aws 
def load_delta(data):
    cur_aws, conn_aws = connect_aws()
    test=[col for col in data.columns.values]   
    for index,row in data.iterrows():
        #query = '''insert into public.iot_dev_status_delta (dev_id, status_expire_time, x, y, z, current_status) \
        #values ('{}','{}','{}','{}','{}','{}')'''.format(*[row[col] for col in data.columns.values])
        query = '''insert into public.iot_dev_status_delta (dev_id, status_time, x, y, z, current_status) values \
         ('{}','{}','{}','{}','{}','{}')'''.format(*[row['dev_id'],row['time_id'],row['x'],row['y'],row['z'],'1'])

        cur_aws.execute(query)
        conn_aws.commit()
        
    cur_aws.close()
    conn_aws.close()


#dont' know why, but when I join delta with status table, it get locked.
# so I have avoided join in the sql statement
#get the latest signal status and find active devices' coordinate
def reset_dev_status(df_xyz_last_filter, dev_reset_list_str):
    sqlDropDelta = (
        f"""
        DROP TABLE IF EXISTS public.iot_dev_status_delta """,)
    sqlCreateDelta = (
        f"""
        CREATE TABLE IF NOT EXISTS public.iot_dev_status_delta (
            dev_id varchar(50), 
            status_time timestamp, 
            x INTEGER, 
            y INTEGER, 
            z INTEGER, 
            current_status INTEGER )""" ,)
    sqlUpdateStatus = (
        f"""
        update public.iot_dev_status as status 
        set current_status = 0
        where status.dev_id in {dev_reset_list_str}
        and status.current_status = 1""", )       
    sqlInsertLatest = (
        f"""
        insert into public.iot_dev_status (dev_id,status_time,x,y,z,current_status) 
        select dev_id,status_time,x,y,z,current_status
        from public.iot_dev_status_delta """,)    
    rds_table_operate.execute(sqlDropDelta)
    rds_table_operate.execute(sqlCreateDelta)
    load_delta(df_xyz_last_filter)
    rds_table_operate.execute(sqlUpdateStatus)    #this is the step hangs(lock) the process if join
    rds_table_operate.execute(sqlInsertLatest)


def form_dataframe(response):
    #function content for form_dataframe(response), response.items() is a multilayer dictionary
    #keys include items, count, scanned count, lastevaluatedkey etc...(Items contains data information)

    #generate dataframe from dictionary
    response_json_str = response['Items']    
    df = pd.io.json.json_normalize(response_json_str)
    df = df.astype({'x': 'int32', 'y': 'int32', 'z': 'int32'})
    
    #date_time_obj = datetime.datetime.strptime(date_time_str, '%Y-%m-%d %H:%M:%S.%f')
    df['time_id_obj'] = pd.to_datetime(df['time_id'], utc=True)

    #get the last record for each deviced, in the last N minutes
    df_xyz_last = df.sort_values(["time_id"], ascending = True) \
                .groupby(['app_id','dev_id'])[['x','y','z','time_id','time_id_obj']] \
                .last() \
                .reset_index()    
    return df_xyz_last



def get_window_data(WINDOWLEN, dict_time):   
    params_dynamodb = config_dynamodb()
    print(params_dynamodb)
    # The boto3 dynamoDB resource, connectoin
    dynamodb_resource = resource(params_dynamodb['resource'],region_name=params_dynamodb['region'])
    table = dynamodb_resource.Table(params_dynamodb['table'])   
      
    fe = Key('date_id').eq(dict_time['utcTodayYesterdayStr'][0]) & \
            Key('time_id').between(dict_time['utcWindowStartStr'],dict_time['utcNowStr']) 
    pe = "date_id, app_id, dev_id, time_id, x, y, z"
    #response = table.query(KeyConditionExpression=fe)
    response = table.query(ProjectionExpression=pe, KeyConditionExpression=fe)
    
    while 'LastEvaluatedKey' in response:
        response = table.query(
            ProjectionExpression=pe,
            KeyConditionExpression=fe,
            ExclusiveStartKey=response['LastEvaluatedKey']
            )
    return response


def define_window_timestamp(WINDOWLEN):    
    time_dict = dict()
    #time window FROM to TO
    time_dict['utcNow'] = datetime.now(timezone.utc)
    time_dict['utcWindowStart'] = time_dict['utcNow'] - timedelta(seconds=WINDOWLEN)
    
    time_dict['utcNowStr'] = time_dict['utcNow'].strftime("%Y-%m-%dT%H:%M:%S").split('.')[0]
    time_dict['utcWindowStartStr'] = time_dict['utcWindowStart'].strftime("%Y-%m-%dT%H:%M:%S").split('.')[0]

    utcToday = time_dict['utcNow'].strftime("%Y%m%d").split('.')[0]
    utcYesterday = (time_dict['utcNow']-timedelta(days=1)).strftime("%Y%m%d").split('.')[0]
    time_dict['utcTodayYesterdayStr'] =  [utcToday, utcYesterday]
    return time_dict


def lambda_handler(event, context):
    # TODO implement
    dev_reset_list = []

    #start time, end time, give 5 minutes to run the deltra function
    #after device is installed
    dict_time = define_window_timestamp(confglobal.WINDOWLEN)
    for key, val in dict_time.items():
        print(key)
        print(val)

    response = get_window_data(confglobal.WINDOWLEN, dict_time)
    
    df_xyz_last = form_dataframe(response)
    print("****records for each device from dynamoDB")
    print(df_xyz_last)
    

    #reset all device or one device; all devicelist is based on lastest update from dynamoDB
    if (len(event['dev_id'])==1) & (event['dev_id'][0]=='all'):
        dev_reset_list = df_xyz_last['dev_id'].unique()
            #print("value3 = " + event['key3'])   
    else:
        dev_reset_list = event['dev_id']  #can be a list of devices instead just one
    df_xyz_last_filter = df_xyz_last[df_xyz_last['dev_id'].isin(dev_reset_list)].copy()
    print("****records to insert")
    print(df_xyz_last_filter)
    #print(dev_reset_list)
        
    dev_reset_list_str = '(\'' + '\',\''.join(dev_reset_list) + '\')' 
    reset_dev_status(df_xyz_last_filter, dev_reset_list_str)
    

    # TODO implement
    return {
       'statusCode': 200,
       'body': json.dumps('insert devices {}!'.format(' '.join(df_xyz_last_filter['dev_id'])))
    }


#test_json = {
#  "dev_id": ["node32_2"],
#  "key3": "999"
#}
#
#response = lambda_handler(test_json, None)
