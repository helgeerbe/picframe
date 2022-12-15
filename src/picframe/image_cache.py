import sqlite3
import os
import time
import logging
import threading
from picframe import get_image_meta

class ImageCache:

    EXTENSIONS = ['.png','.jpg','.jpeg','.heif','.heic']
    EXIF_TO_FIELD = {'EXIF FNumber': 'f_number',
                     'Image Make': 'make',
                     'Image Model': 'model',
                     'EXIF ExposureTime': 'exposure_time',
                     'EXIF ISOSpeedRatings': 'iso',
                     'EXIF FocalLength': 'focal_length',
                     'EXIF Rating': 'rating',
                     'EXIF LensModel': 'lens',
                     'EXIF DateTimeOriginal': 'exif_datetime',
                     'IPTC Keywords': 'tags',
                     'IPTC Caption/Abstract': 'caption',
                     'IPTC Object Name': 'title'}


    def __init__(self, picture_dir, follow_links, db_file, geo_reverse, portrait_pairs=False):
        # TODO these class methods will crash if Model attempts to instantiate this using a
        # different version from the latest one - should this argument be taken out?
        self.__modified_folders = []
        self.__modified_files = []
        self.__cached_file_stats = [] # collection shared between threads
        self.__logger = logging.getLogger("image_cache.ImageCache")
        self.__logger.debug('Creating an instance of ImageCache')
        self.__picture_dir = picture_dir
        self.__follow_links = follow_links
        self.__db_file = db_file
        self.__geo_reverse = geo_reverse
        self.__portrait_pairs = portrait_pairs #TODO have a function to turn this on and off?
        self.__db = self.__create_open_db(self.__db_file)
        self.__db_write_lock = threading.Lock() # lock to serialize db writes between threads
        # NB this is where the required schema is set
        self.__update_schema(3)

        self.__keep_looping = True
        self.__pause_looping = False
        self.__shutdown_completed = False
        self.__purge_files = False

        t = threading.Thread(target=self.__loop)
        t.start()


    def __loop(self):
        while self.__keep_looping:
            if not self.__pause_looping:
                self.update_cache()
                time.sleep(2.0)
            time.sleep(0.01)
        self.__db_write_lock.acquire()
        self.__db.commit() # close after update_cache finished for last time
        self.__db_write_lock.release()
        self.__db.close()
        self.__shutdown_completed = True


    def pause_looping(self, value):
        self.__pause_looping = value


    def stop(self):
        self.__keep_looping = False
        while not self.__shutdown_completed:
            time.sleep(0.05) # make function blocking to ensure staged shutdown

    def purge_files(self):
        self.__purge_files = True

    def update_cache(self):
        """Update the cache database with new and/or modified files
        """

        self.__logger.debug('Updating cache')


        # If the current collection of updated files is empty, check for disk-based changes
        if not self.__modified_files:
            self.__logger.debug('No unprocessed files in memory, checking disk')
            self.__modified_folders = self.__get_modified_folders()
            self.__modified_files = self.__get_modified_files(self.__modified_folders)
            self.__logger.debug('Found %d new files on disk', len(self.__modified_files))

        # While we have files to process and looping isn't paused
        while self.__modified_files and not self.__pause_looping:
            file = self.__modified_files.pop(0)
            self.__logger.debug('Inserting: %s', file)
            self.__insert_file(file)

        # If we've process all files in the current collection, update the cached folder info
        if not self.__modified_files:
            self.__update_folder_info(self.__modified_folders)
            self.__modified_folders.clear()

        # If looping is still not paused, remove any files or folders from the db that are no longer on disk
        if not self.__pause_looping:
            self.__purge_missing_files_and_folders()

        # Commit the current set of changes
        self.__db_write_lock.acquire()
        self.__db.commit()
        self.__db_write_lock.release()


    def query_cache(self, where_clause, sort_clause = 'fname ASC'):
        cursor = self.__db.cursor()
        cursor.row_factory = None # we don't want the "sqlite3.Row" setting from the db here...
        try:
            if not self.__portrait_pairs: # TODO SQL insertion? Does it matter in this app?
                sql = """SELECT file_id FROM all_data WHERE {0} ORDER BY {1}
                    """.format(where_clause, sort_clause)
                return cursor.execute(sql).fetchall()
            else: # make two SELECTS
                sql = """SELECT
                            CASE
                                WHEN is_portrait = 0 THEN file_id
                                ELSE -1
                            END
                            FROM all_data WHERE {0} ORDER BY {1}
                                        """.format(where_clause, sort_clause)
                full_list = cursor.execute(sql).fetchall()
                sql = """SELECT file_id FROM all_data
                            WHERE ({0}) AND is_portrait = 1 ORDER BY {1}
                                        """.format(where_clause, sort_clause)
                pair_list = cursor.execute(sql).fetchall()
                newlist = []
                skip_portrait_slot = False
                for i in range(len(full_list)):
                    if full_list[i][0] != -1:
                        newlist.append(full_list[i])
                    elif skip_portrait_slot:
                        skip_portrait_slot = False
                        continue
                    elif pair_list:
                        elem = pair_list.pop(0)
                        if pair_list:
                            elem += pair_list.pop(0)
                            # Here, we just doubled-up a set of portrait images.
                            # Skip the next available "portrait slot" as it's unneeded.
                            skip_portrait_slot = True
                        newlist.append(elem)
                return newlist
        except:
            return []


    def get_file_info(self, file_id):
        if not file_id: return None
        sql = "SELECT * FROM all_data where file_id = {0}".format(file_id)
        row = self.__db.execute(sql).fetchone()
        try:
            if row is not None and row['last_modified']  != os.path.getmtime(row['fname']):
                self.__logger.debug('Cache miss: File %s changed on disk', row['fname'])
                self.__insert_file(row['fname'], file_id)
                row = self.__db.execute(sql).fetchone() # description inserted in table
        except OSError:
            self.__logger.warning("Image '%s' does not exists or is inaccessible" %row['fname'])
        if row is not None and row['latitude'] is not None and row['longitude'] is not None and row['location'] is None:
            if self.__get_geo_location(row['latitude'], row['longitude']):
                row = self.__db.execute(sql).fetchone() # description inserted in table
        sql = "UPDATE file SET displayed_count = displayed_count + 1, last_displayed = ? WHERE file_id = ?"
        starttime = round(time.time() * 1000)
        self.__db_write_lock.acquire()
        waittime = round(time.time() * 1000)
        self.__db.execute(sql, (time.time(), file_id)) # Add file stats 
        self.__db_write_lock.release()
        now = round(time.time() * 1000)
        self.__logger.debug('Update file stats: Wait for %d ms and need %d ms for update ', waittime - starttime, now - waittime)
        return row # NB if select fails (i.e. moved file) will return None

    def get_column_names(self):
        sql = "PRAGMA table_info(all_data)"
        rows = self.__db.execute(sql).fetchall()
        return [row['name'] for row in rows]

    def __get_geo_location(self, lat, lon): # TODO periodically check all lat/lon in meta with no location and try again
        location = self.__geo_reverse.get_address(lat, lon)
        if len(location) == 0:
            return False #TODO this will continue to try even if there is some permanant cause
        else:
            sql = "INSERT OR REPLACE INTO location (latitude, longitude, description) VALUES (?, ?, ?)"
            starttime = round(time.time() * 1000)
            self.__db_write_lock.acquire()
            waittime = round(time.time() * 1000)
            self.__db.execute(sql, (lat, lon, location))
            self.__db_write_lock.release()
            now = round(time.time() * 1000)
            self.__logger.debug('Update location: Wait for db %d ms and need %d ms for update ', waittime - starttime, now - waittime)
            return True


    def __create_open_db(self, db_file):
        sql_folder_table = """
            CREATE TABLE IF NOT EXISTS folder (
                folder_id INTEGER NOT NULL PRIMARY KEY,
                name TEXT UNIQUE NOT NULL,
                last_modified REAL DEFAULT 0 NOT NULL
            )"""

        sql_file_table = """
            CREATE TABLE IF NOT EXISTS file (
                file_id INTEGER NOT NULL PRIMARY KEY,
                folder_id INTEGER NOT NULL,
                basename  TEXT NOT NULL,
                extension TEXT NOT NULL,
                last_modified REAL DEFAULT 0 NOT NULL,
                UNIQUE(folder_id, basename, extension)
            )"""

        sql_meta_table = """
            CREATE TABLE IF NOT EXISTS meta (
                file_id INTEGER NOT NULL PRIMARY KEY,
                orientation INTEGER DEFAULT 1 NOT NULL,
                exif_datetime REAL DEFAULT 0 NOT NULL,
                f_number REAL DEFAULT 0 NOT NULL,
                exposure_time TEXT,
                iso REAL DEFAULT 0 NOT NULL,
                focal_length TEXT,
                make TEXT,
                model TEXT,
                lens TEXT,
                rating INTEGER,
                latitude REAL,
                longitude REAL,
                width INTEGER DEFAULT 0 NOT NULL,
                height INTEGER DEFAULT 0 NOT NULL,
                title TEXT,
                caption TEXT,
                tags TEXT
            )"""

        sql_meta_index = """
            CREATE INDEX IF NOT EXISTS exif_datetime ON meta (exif_datetime)"""

        sql_location_table = """
            CREATE TABLE IF NOT EXISTS location (
                id INTEGER NOT NULL PRIMARY KEY,
                latitude REAL,
                longitude REAL,
                description TEXT,
                UNIQUE (latitude, longitude)
            )"""

        sql_db_info_table = """
            CREATE TABLE IF NOT EXISTS db_info (
                schema_version INTEGER NOT NULL
            )"""

        # Combine all important data in a single view for easy accesss
        # Although we can't control the layout of the view when using 'meta.*', we want it
        # all and that seems better than enumerating (and maintaining) each column here.
        sql_all_data_view = """
            CREATE VIEW IF NOT EXISTS all_data
            AS
            SELECT
                folder.name || "/" || file.basename || "." || file.extension AS fname,
                file.last_modified,
                meta.*,
                meta.height > meta.width as is_portrait,
                location.description as location
            FROM file
                INNER JOIN folder
                    ON folder.folder_id = file.folder_id
                LEFT JOIN meta
                    ON file.file_id = meta.file_id
                LEFT JOIN location
                    ON location.latitude = meta.latitude AND location.longitude = meta.longitude
            """

        # trigger to automatically delete file records when associated folder records are deleted
        sql_clean_file_trigger = """
            CREATE TRIGGER IF NOT EXISTS Clean_File_Trigger
            AFTER DELETE ON folder
            FOR EACH ROW
            BEGIN
                DELETE FROM file WHERE folder_id = OLD.folder_id;
            END"""

        # trigger to automatically delete meta records when associated file records are deleted
        sql_clean_meta_trigger = """
            CREATE TRIGGER IF NOT EXISTS Clean_Meta_Trigger
            AFTER DELETE ON file
            FOR EACH ROW
            BEGIN
                DELETE FROM meta WHERE file_id = OLD.file_id;
            END"""

        db = sqlite3.connect(db_file, check_same_thread=False) # writing only done in loop thread, reading in this so should be safe
        db.row_factory = sqlite3.Row # make results accessible by field name
        for item in (sql_folder_table, sql_file_table, sql_meta_table, sql_location_table, sql_meta_index,
                    sql_all_data_view, sql_db_info_table, sql_clean_file_trigger, sql_clean_meta_trigger):
            db.execute(item)

        return db


    def __update_schema(self, required_db_schema_version):
        sql_select = "SELECT schema_version from db_info"
        schema_version = self.__db.execute(sql_select).fetchone()
        schema_version = 1 if not schema_version else schema_version[0]

        # DB is newer than the application. The User needs to upgrade...
        if schema_version > required_db_schema_version:
            raise ValueError("Database schema is newer than the application. Update the application.")

        # Here, we need to update the db schema as necessary
        if schema_version < required_db_schema_version:

            if schema_version <= 1:
                # Migrate to db schema v2
                # Update the all_data view to only contain files from folders that currently exist.
                # This allows stored data to be retained for files in folders that may be temporarily
                #   missing while not causing issues for the slideshow.
                self.__db.execute("DROP VIEW all_data")
                self.__db.execute("ALTER TABLE folder ADD COLUMN missing INTEGER DEFAULT 0 NOT NULL")
                self.__db.execute("""
                    CREATE VIEW IF NOT EXISTS all_data
                    AS
                    SELECT
                        folder.name || "/" || file.basename || "." || file.extension AS fname,
                        file.last_modified,
                        meta.*,
                        meta.height > meta.width as is_portrait,
                        location.description as location
                    FROM file
                        INNER JOIN folder
                            ON folder.folder_id = file.folder_id
                        LEFT JOIN meta
                            ON file.file_id = meta.file_id
                        LEFT JOIN location
                            ON location.latitude = meta.latitude AND location.longitude = meta.longitude
                    WHERE folder.missing = 0
                    """)

            if schema_version <= 2:
                # Migrate to db schema v3
                # Add "displayed statistics" fields to the file table (useful for slideshow debugging)
                self.__db.execute("ALTER TABLE file ADD COLUMN displayed_count INTEGER default 0 NOT NULL")
                self.__db.execute("ALTER TABLE file ADD COLUMN last_displayed REAL DEFAULT 0 NOT NULL")

            # Finally, update the db's schema version stamp to the app's requested version
            self.__db.execute('DELETE FROM db_info')
            self.__db.execute('INSERT INTO db_info VALUES(?)', (required_db_schema_version,))
            self.__db.commit()

    # --- Returns a set of folders matching any of
    #     - Found on disk, but not currently in the 'folder' table
    #     - Found on disk, but newer than the associated record in the 'folder' table
    #     - Found on disk, but flagged as 'missing' in the 'folder' table
    # --- Note that all folders returned currently exist on disk
    def __get_modified_folders(self):
        out_of_date_folders = []
        sql_select = "SELECT * FROM folder WHERE name = ?"
        for dir in [d[0] for d in os.walk(self.__picture_dir, followlinks=self.__follow_links)]:
            if os.path.basename(dir)[0] == '.': continue # ignore hidden folders
            mod_tm = int(os.stat(dir).st_mtime)
            found = self.__db.execute(sql_select, (dir,)).fetchone()
            if not found or found['last_modified'] < mod_tm or found['missing'] == 1:
                out_of_date_folders.append((dir, mod_tm))
        return out_of_date_folders


    def __get_modified_files(self, modified_folders):
        out_of_date_files = []
        #sql_select = "SELECT fname, last_modified FROM all_data WHERE fname = ? and last_modified >= ?"
        sql_select = """
        SELECT file.basename, file.last_modified
            FROM file
                INNER JOIN folder
                    ON folder.folder_id = file.folder_id
            WHERE file.basename = ? AND file.extension = ? AND folder.name = ? AND file.last_modified >= ?
        """
        for dir,_date in modified_folders:
            for file in os.listdir(dir):
                base, extension = os.path.splitext(file)
                if (extension.lower() in ImageCache.EXTENSIONS
                        and not '.AppleDouble' in dir and not file.startswith('.')): # have to filter out all the Apple junk
                    full_file = os.path.join(dir, file)
                    mod_tm =  os.path.getmtime(full_file)
                    found = self.__db.execute(sql_select, (base, extension.lstrip("."), dir, mod_tm)).fetchone()
                    if not found:
                        out_of_date_files.append(full_file)
        return out_of_date_files


    def __insert_file(self, file, file_id = None):
        file_insert = "INSERT OR REPLACE INTO file(folder_id, basename, extension, last_modified) VALUES((SELECT folder_id from folder where name = ?), ?, ?, ?)"
        file_update = "UPDATE file SET folder_id = (SELECT folder_id from folder where name = ?), basename = ?, extension = ?, last_modified = ? WHERE file_id = ?"
        # Insert the new folder if it's not already in the table. Update the missing field separately.
        folder_insert = "INSERT OR IGNORE INTO folder(name) VALUES(?)"
        folder_update = "UPDATE folder SET missing = 0 where name = ?"

        mod_tm =  os.path.getmtime(file)
        dir, file_only = os.path.split(file)
        base, extension = os.path.splitext(file_only)

        # Get the file's meta info and build the INSERT statement dynamically
        meta = self.__get_exif_info(file)
        meta_insert = self.__get_meta_sql_from_dict(meta)
        vals = list(meta.values())
        vals.insert(0, file)

        # Insert this file's info into the folder, file, and meta tables
        self.__db_write_lock.acquire()
        self.__db.execute(folder_insert, (dir,))
        self.__db.execute(folder_update, (dir,))
        if file_id is None:
            self.__db.execute(file_insert, (dir, base, extension.lstrip("."), mod_tm))
        else:
            self.__db.execute(file_update, (dir, base, extension.lstrip("."), mod_tm, file_id))
        self.__db.execute(meta_insert, vals)
        self.__db_write_lock.release()


    def __update_folder_info(self, folder_collection):
        update_data = []
        sql = "UPDATE folder SET last_modified = ?, missing = 0 WHERE name = ?"
        for folder, modtime in folder_collection:
            update_data.append((modtime, folder))
        self.__db_write_lock.acquire()
        self.__db.executemany(sql, update_data)
        self.__db_write_lock.release()


    def __get_meta_sql_from_dict(self, dict):
        columns = ', '.join(dict.keys())
        ques = ', '.join('?' * len(dict.keys()))
        return 'INSERT OR REPLACE INTO meta(file_id, {0}) VALUES((SELECT file_id from all_data where fname = ?), {1})'.format(columns, ques)


    def __purge_missing_files_and_folders(self):
        # Find folders in the db that are no longer on disk
        folder_id_list = []
        for row in self.__db.execute('SELECT folder_id, name from folder'):
            if not os.path.exists(row['name']):
                folder_id_list.append([row['folder_id']])

        # Flag or delete any non-existent folders from the db. Note, deleting will automatically
        # remove orphaned records from the 'file' and 'meta' tables
        if len(folder_id_list):
            self.__db_write_lock.acquire()
            if self.__purge_files:
                self.__db.executemany('DELETE FROM folder WHERE folder_id = ?', folder_id_list)
            else:
                self.__db.executemany('UPDATE folder SET missing = 1 WHERE folder_id = ?', folder_id_list)
            self.__db_write_lock.release()

        # Find files in the db that are no longer on disk
        if self.__purge_files:
            file_id_list = []
            for row in self.__db.execute('SELECT file_id, fname from all_data'):
                if not os.path.exists(row['fname']):
                    file_id_list.append([row['file_id']])

            # Delete any non-existent files from the db. Note, this will automatically
            # remove matching records from the 'meta' table as well.
            if len(file_id_list):
                self.__db_write_lock.acquire()
                self.__db.executemany('DELETE FROM file WHERE file_id = ?', file_id_list)
                self.__db_write_lock.release()
            self.__purge_files = False

    def __get_exif_info(self, file_path_name):
        exifs = get_image_meta.GetImageMeta(file_path_name)
        # Dict to store interesting EXIF data
        # Note, the 'key' must match a field in the 'meta' table
        e = {}

        e['orientation'] = exifs.get_orientation()

        width, height = exifs.get_size()
        ext = os.path.splitext(file_path_name)[1].lower()
        if ext not in ('.heif','.heic') and e['orientation'] in (5, 6, 7, 8):
            width, height = height, width # swap values
        e['width'] = width
        e['height'] = height


        e['f_number'] = exifs.get_exif('EXIF FNumber')
        e['make'] = exifs.get_exif('Image Make')
        e['model'] = exifs.get_exif('Image Model')
        e['exposure_time'] = exifs.get_exif('EXIF ExposureTime')
        e['iso'] =  exifs.get_exif('EXIF ISOSpeedRatings')
        e['focal_length'] =  exifs.get_exif('EXIF FocalLength')
        e['rating'] = exifs.get_exif('Image Rating')
        e['lens'] = exifs.get_exif('EXIF LensModel')
        e['exif_datetime'] = None
        val = exifs.get_exif('EXIF DateTimeOriginal')
        if val != None:
            # Remove any subsecond portion of the DateTimeOriginal value. According to the spec, it's
            # not valid here anyway (should be in SubSecTimeOriginal), but it does exist sometimes.
            val = val.split('.', 1)[0]
            try:
                e['exif_datetime'] = time.mktime(time.strptime(val, '%Y:%m:%d %H:%M:%S'))
            except:
                pass

        # If we still don't have a date/time, just use the file's modificaiton time
        if e['exif_datetime'] == None:
            e['exif_datetime'] = os.path.getmtime(file_path_name)

        gps = exifs.get_location()
        lat = gps['latitude']
        lon = gps['longitude']
        e['latitude'] = round(lat, 4) if lat is not None else lat #TODO sqlite requires (None,) to insert NULL
        e['longitude'] = round(lon, 4) if lon is not None else lon

        #IPTC
        e['tags'] = exifs.get_exif('IPTC Keywords')
        e['title'] = exifs.get_exif('IPTC Object Name')
        e['caption'] = exifs.get_exif('IPTC Caption/Abstract')


        return e


# If being executed (instead of imported), kick it off...
if __name__ == "__main__":
    cache = ImageCache(picture_dir='/home/pi/Pictures', follow_links=False, db_file='/home/pi/db.db3', geo_reverse=None)
    #cache.update_cache()
    # items = cache.query_cache("make like '%google%'", "exif_datetime asc")
    #info = cache.get_file_info(12)
