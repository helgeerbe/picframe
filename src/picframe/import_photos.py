import os, sys, time, logging, warnings, json, re, pytz, ntplib, urllib3, requests
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode, urlparse
from requests.exceptions import HTTPError

logger = logging.getLogger(__name__)

class LoginError(Exception):
    pass

class GetPlaylistsError(Exception):
    pass

class FolderCreationError(Exception):
    pass

class GetMediaError(Exception):
    pass

class import_photos:
    """Class to import photos from third-party services to local filesystem."""

    def __init__(self):
        pass

def get_ntp_time():
    """Gets the current time from an NTP server."""
    try:
        client = ntplib.NTPClient()
        response = client.request('pool.ntp.org', version=3)
        return datetime.fromtimestamp(response.tx_time, tz=timezone.utc)
    except Exception as e:
        print(f"Error getting NTP time: {e}")
        return None
def get_local_time():
    """Gets the current local time."""
    return datetime.now(tz=timezone.utc)  



def wait_for_directory(path, timeout=10):
    """Waits for a directory to be created, timeout: The maximum time to wait in seconds (default: 30)."""
    start_time = time.time()
    while not os.path.exists(path):
        time.sleep(1)
        if time.time() - start_time > timeout:
            return False
    return True

def create_valid_folder_name(string):
    """Converts a string to a valid folder name."""
    # Replace invalid characters with underscores
    string = re.sub(r'[\\/:*?"<>|]', '_', string)

    # Remove leading/trailing whitespace
    string = string.strip()

    return string

def create_authorized_client(username: str, password: str, login_url: str):
    """Submits login form and returns valid session."""    
    data = {
        'email': username,
        'password': password
    }
    with requests.Session() as session:
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        response = session.post(login_url, headers=headers, data=data)
    return session

def get_playlist_names(session, playlist_url, frame_key):
    """Retrieves playlist names that match key and last_updated_date from nixplay cloud."""
    json = session.get(playlist_url).json()
    playtlists = []
    for plist in json:
        if (re.search(frame_key + "$", plist["playlist_name"])):
            data = {
                    "id": plist["id"],
                    "playlist_name": plist["playlist_name"],
                    "last_updated_date": plist["last_updated_date"]
                    }
            playlists.append(data)
    return playlists

def get_playlist_media(session, playlist_url, item_path, playlists_to_update):
    """Retrieves individual media item metadata from nixplay cloud/"""
    media_items = []
    for item_id in playlists_to_update:
        url = playlist_url + str(item_id[0]) + '/' + item_path
        json = session.get(url).json()
        for slide in json[item_path]:
            data = {
                    "mediaItemId": slide["mediaItemId"],
                    "originalUrl": slide["originalUrl"]
                    }
            media_items.append(data)
    return media_items

def compare_modified_times(subdirectory, date):
    """Checks if nixplay playlist modified is > local directory (always use UTC)"""
    local_mtime = os.path.getmtime(subdirectory)
    local_mtime = datetime.fromtimestamp(local_mtime, tz=timezone.utc)
    nix_mtime = datetime.strptime(date, '%Y-%m-%dT%H:%M:%S.%fZ')
    nix_mtime = nix_mtime.replace(tzinfo=pytz.utc)
    diff = local_mtime - nix_mtime
    # if diff is negative, nixcloud playlist has changed - we must check local contents for adds/changes/deletes
    return diff

if __name__ == '__main__':
    print("starting")
    warnings.filterwarnings("ignore", category=urllib3.exceptions.InsecureRequestWarning)
    username  = os.environ['NIXPLAY_ACCOUNT_USERNAME']
    password  = os.environ['NIXPLAY_ACCOUNT_PASSWORD']
    login_url = "https://api.nixplay.com/www-login/"
    playlist_url = "https://api.nixplay.com/v3/playlists/"
    item_path = "slides"  # url is: playlist_url + list_id + '/' + item_path
    frame_key = "FR001"
    local_pictures_path = "~/Pictures/"

# LOGIN
    try:
        session = create_authorized_client(username, password, login_url)
        # print(vars(session))
        if session.cookies.get("prod.session.id") is None:
            raise LoginError("Bad Credentials")
    except LoginError as e:
        print(f"Login failed: {e}")
        print("Exiting")
        sys.exit()
    except Exception as e:
        print(f"An error occurred: {e}")
    print("logged in")

# GET PLAYLIST NAMES 
    playlists = []
    try:
        playlists = get_playlist_names(session, playlist_url, frame_key)

    except GetPlaylistsError as e:
        print(f"Login failed: {e}")
    except Exception as e:
        print(f"An error occurred: {e}")
    print("got playlists")

# CHECK OR CREATE SUBDIRECTORIES
    print("checking for playlist updates")
    playlists_to_update = []
    flag = 0
    for playlist in playlists:
        folder_name = create_valid_folder_name(playlist["playlist_name"])  # Normalize name just in case (edge case of overwrites)
        subdirectory = os.path.expanduser(local_pictures_path + folder_name + "/")
            
        if os.path.isdir(subdirectory):
            diff = compare_modified_times(subdirectory, playlist["last_updated_date"])
            if diff < timedelta(0):
                playlists_to_update.append((playlist["id"], playlist["playlist_name"], subdirectory))
                flag = 1
        else:
            # Create new directory
            try:
                os.makedirs(subdirectory, mode=0o700, exist_ok=False)
                if wait_for_directory(subdirectory, timeout=10):
                    playlists_to_update.append((playlist["id"], playlist["playlist_name"], subdirectory))
                else:
                    raise Exception("Creating new playlist directory timed out")

            except FolderCreationError as e:
                print(f"Folder creation failed: {e}")
            except Exception as e:
                print(f"An error occurred: {e}")
            flag = 1
            print("created new directories")
    if flag == 0:
        print("Nothing to update")    

#   GET MEDIA TO ADD / CHANGE / DELETE
    media_items = []
    media_to_add = []
    media_to_delete = []

    try:
        media_items = get_playlist_media(session, playlist_url, item_path, playlists_to_update)

    except GetMediaError as e:
        print(f"Error getting media item names: {e}")
    except Exception as e:
        print(f"An error occurred: {e}")

    print(media_items)

# NOTES:
#   when copying media, item should be named with the original filename, followed by a separator token and the unique nix mediaItemId
#   ** in playlist / slides some photos do not have a filename key!
#   individual media items can be modified on nixplay - rotated, captioned, favorited, ?