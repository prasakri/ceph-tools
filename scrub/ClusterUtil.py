import boto
import boto.s3.connection
import Constants
from ParserUtil import ParserUtil
from rgwadmin import RGWAdmin
from Util import Util


class ClusterUtil:
    def __init__(self, cluster, logger):
        self.__cluster = cluster
        self.logger = logger

    def __get_cluster(self):
        return self.__cluster

    def prepare_rgwadmin_conn(self):
        admin_conn = RGWAdmin(access_key=self.__get_cluster().admin_access_key, secret_key=self.__get_cluster().admin_secret_key,
                              server=self.__get_cluster().host, secure=False)
        return admin_conn

    def get_bucket_owner_keys(self, bucket_name):
        admin_conn = self.prepare_rgwadmin_conn()
        try:
            bucket_meta = admin_conn.get_metadata("bucket", bucket_name)
            owner_uid = bucket_meta['data']['owner']
            user = admin_conn.get_user(owner_uid)
            return {
                "access_key": user['keys'][0]['access_key'],
                "secret_key": user['keys'][0]['secret_key']
            }
        except Exception as ex:
            return None

    def prepare_s3_conn(self, bucket_name):
        owner_keys = self.get_bucket_owner_keys(bucket_name)
        return self.get_s3_conn(owner_keys["access_key"], owner_keys["secret_key"])

    def get_s3_conn(self, access_key, secret_key):
        conn = boto.connect_s3(
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            host=self.__get_cluster().host,
            is_secure=False,  # uncomment if you are not using ssl
            calling_format=boto.s3.connection.OrdinaryCallingFormat(),
        )
        return conn

    def get_bucket(self, bucket_name):
        conn = self.prepare_s3_conn(bucket_name)
        bucket = conn.get_bucket(bucket_name)
        return bucket

    def get_all_buckets(self, user_id):
        admin_conn = self.prepare_rgwadmin_conn()
        user_meta = admin_conn.get_metadata("user", user_id)
        user = user_meta['data']['keys'][0]

        s3_conn = self.get_s3_conn(user['access_key'], user['secret_key'])
        return s3_conn.get_all_buckets()

    def get_object(self, bucket_name, object_name):
        try:
            bucket = self.get_bucket(bucket_name)
            object = bucket.lookup(object_name)
            return object
        except Exception as ex:
            return None

    def get_objects(self, bucket_name, max_objects=Constants.MAX_NO_OF_OBJECTS, keys_per_query=Constants.KEYS_PER_QUERY_DEFAULT, marker=""):
        bucket = self.get_bucket(bucket_name)
        object_list = []
        total_objs_retrieved = 0

        while total_objs_retrieved < max_objects:
            keys_per_query = min(max_objects - total_objs_retrieved, keys_per_query)
            objects = bucket.get_all_keys(max_keys=keys_per_query, marker=marker)
            objs_retrieved = len(objects)

            # Break if you have retrieved all the objects in the bucket
            if objs_retrieved == 0:
                break

            total_objs_retrieved = total_objs_retrieved + objs_retrieved
            self.logger.info("Retrieved: %d" % total_objs_retrieved)

            last_object = None
            for object in objects:
                object_list.append(object)
                last_object = object

            marker = last_object.name.encode('utf-8')

        return object_list

    def get_all_objects(self, bucket_name):
        return self.get_objects(bucket_name)

    # Gets the S3Object as input
    def download_object(self, object, file_name):
        object.get_contents_to_filename(file_name)

    def get_size_from_pool(self, ctx, rados_object_name):
        stat = ctx.stat(str(rados_object_name))
        size = ParserUtil.extract_size_from_stat(str(stat))
        return size

    def get_object_owner_uid(self, bucket_name):
        try:
            admin_conn = self.prepare_rgwadmin_conn()
            bucket_meta = admin_conn.get_metadata("bucket", bucket_name)
            owner_uid = bucket_meta['data']['owner']
            return owner_uid
        except Exception as ex:
            return None

    def get_bucket_stats(self, bucket_name, admin_host):
        command = Constants.COMMAND_BUCKET_STATS % bucket_name
        bucket_stats_raw = Util.run_command_remote(command, admin_host)
        bucket_stats = Util.parse_json(bucket_stats_raw)
        return bucket_stats

    def get_bucket_marker(self, bucket_name):
        admin_conn = self.prepare_rgwadmin_conn()
        bucket_meta = admin_conn.get_metadata("bucket", bucket_name)
        return bucket_meta["data"]["bucket"]["marker"]

    def get_num_of_objects(self, bucket_name, admin_host):
        bucket_stats = self.get_bucket_stats(bucket_name, admin_host)
        return int(bucket_stats["usage"]["rgw.main"]["num_objects"])

    @staticmethod
    def get_rados_object_name(bucket_marker, object_name):
        return Constants.RADOS_OBJECT_NAME_FORMAT % (bucket_marker, object_name)
