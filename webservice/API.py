import os
from glob import glob
from secrets import token_hex
from threading import Thread
from time import sleep
import json
import time

import cv2
import psutil
from flask import Flask, request, jsonify, abort
from main.models import *
from requests import post
from werkzeug.utils import secure_filename
from flask import Flask, request, jsonify, abort, Response
import requests 
proc_exists = (lambda name: [p for p in psutil.process_iter() if p.name() in name])

CACHE_DIR = "webservice/cache"
os.makedirs(CACHE_DIR, exist_ok=True)
CACHE_EXPIRE_SECONDS = 7 * 24 * 3600  # یک هفته (یا 24*3600 برای 24 ساعت)

def get_cache_path(hash):
    return os.path.join(CACHE_DIR, f"{hash}.json")

def get_lock_path(hash):
    return os.path.join(CACHE_DIR, f"{hash}.lock")

def read_cache(hash):
    cache_path = get_cache_path(hash)
    lock_path = get_lock_path(hash)
    wait = 0
    while os.path.exists(lock_path) and wait < 10:
        time.sleep(0.1)
        wait += 0.1
    if not os.path.exists(cache_path):
        return None
    if time.time() - os.path.getmtime(cache_path) > CACHE_EXPIRE_SECONDS:
        os.remove(cache_path)
        return None
    with open(cache_path, "r") as f:
        return json.load(f)

def write_cache(hash, data):
    cache_path = get_cache_path(hash)
    lock_path = get_lock_path(hash)
    open(lock_path, "w").close()
    try:
        with open(cache_path, "w") as f:
            json.dump(data, f)
    finally:
        os.remove(lock_path)

def clean_cache():
    now = time.time()
    for fname in os.listdir(CACHE_DIR):
        if fname.endswith(".json"):
            fpath = os.path.join(CACHE_DIR, fname)
            if os.path.isfile(fpath) and now - os.path.getmtime(fpath) > CACHE_EXPIRE_SECONDS:
                os.remove(fpath)
        elif fname.endswith(".lock"):
            fpath = os.path.join(CACHE_DIR, fname)
            if os.path.isfile(fpath) and now - os.path.getmtime(fpath) > 60:
                os.remove(fpath)

def dhash(image, hashSize=8):
    if len(image.shape) == 3:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    else:
        gray = image
    resized = cv2.resize(gray, (hashSize + 1, hashSize))
    diff = resized[:, 1:] > resized[:, :-1]
    return str(sum([2 ** i for (i, v) in enumerate(diff.flatten()) if v]))


for proc in proc_exists(['python3']):
    try:
        run_c = proc.cmdline()
        if len(run_c) >= 2:
            if "API.py" in run_c[1] and proc.pid != os.getpid():
                proc.kill()
    except psutil.NoSuchProcess:
        pass

UPLOAD_FOLDER = 'webservice/uploads'
urls_file = 'file_urls.csv'
base_url = "https://boomilia.com/media/media/"
BASE62 = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"

white_list_ips = ['94.182.89.152']

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 16 * 1000 * 1000
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['SESSION_TYPE'] = 'filesystem'
app.secret_key = token_hex(16)
caching = {}

search_services = list(range(len(glob(r"main/stacks/*"))))


def decode(string, alphabet=BASE62) -> int:
    base, strlen = len(alphabet), len(string)
    return sum(alphabet.index(d) * (base ** (strlen - (i + 1))) for i, d in enumerate(string))


in_process = False
bakery_queue = {}
waiters = []


# block unknown ips
@app.before_request
def limit_remote_addr():
    if request.remote_addr not in white_list_ips:
        return abort(403)


@app.route("/img_search/", methods=['GET', 'POST'])
def img_search():
    clean_cache()
    try:
        # User IP
        # Target post Tag
        # Describe target in one word
        m_rs = {"user": "", "tag": request.args.get("tag", ""), "word": request.args.get("word", "")}  # Method Results
        # `tag` & `word` methods are OPTIONAL, `user` method is required.
        if "user" in request.args:
            m_rs["user"] = request.args.get("user")
        else:
            return jsonify({'mgs': "error", 'error': f"No selected user method"}), 400

        if not m_rs['user']:
            return jsonify({'mgs': "error", 'error': "No selected user method"}), 400

        if 'file' not in request.files:
            return jsonify({'mgs': "error", 'error': "No selected file"})
        file = request.files['file']
        if file.filename == '':
            return jsonify({'mgs': "error", 'error': "File name is empty"})
        # if bakery_queue.get(user_ip) and bakery_queue[user_ip]["file_name"] == file.filename:
        #     user = bakery_queue[user_ip]
        #     user["step"] += 1
        #     user["continue"] = user["step"] != len(search_services) - 1
        # else:
        #     bakery_queue[user_ip] = {"step": 0, "continue": True, "file_name": file.filename}
        #     user = bakery_queue[user_ip]
        res = {}
        if file:
            if m_rs['user'] not in waiters:
                waiters.append(m_rs['user'])
            else:
                return jsonify({'mgs': "error", 'error': "You have already an open process"})
            while waiters[0] != m_rs['user']:
                sleep(1)
            in_process = True
            filename = secure_filename(file.filename)
            fp = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(fp)
            image = cv2.imread(fp)
            if image is None:
                return
            image = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
            get_dhash = dhash(image)
            results = read_cache(get_dhash)
            if results is not None:
                res = {'msg': "ok", 'result': results}
                waiters.pop(waiters.index(m_rs['user']))
            else:
                try:
                    result, added_counts = [], 0

                    def add_res(i):
                        nonlocal added_counts
                        try:
                            result.extend(
                                post(
                                    f'http://127.0.0.1:{1950 + i}/process',
                                    data={'fp': fp, 'tag': m_rs['tag']},
                                    timeout=600
                                ).json()
                            )
                        except:
                            print(f"ERROR stack{i}.npz service without response!")
                        added_counts += 1

                    for i in search_services:
                        Thread(target=add_res, args=(i,)).start()

                    while added_counts != len(search_services):
                        sleep(.5)

                    result = sorted(result, key=lambda item: item[1])[:15]
                    results = []
                    for i in result:
                        img = Images().where(Images.id == decode(i[0])).first()
                        results.append(
                            {
                                "image": base_url + img.URL,
                                "title": img.info.title,
                                "seo_id": img.info.seo_id,
                                "score": i[1],
                            }
                        )

                    res = {'msg': "ok", 'result': results}
                    # if not any([m_rs['tag'], m_rs['word']]):
                    write_cache(get_dhash, results)
                    # if not user.get("continue"):
                    #     bakery_queue.pop(user_ip)
                except Exception as error:
                    print(str(error), "Systemic Error")
                    res = {'msg': "error", "error": "Systemic Error"}
                os.path.exists(fp) and os.remove(fp)
                waiters.pop(waiters.index(m_rs['user']))
    except Exception as error:
        print(str(error), "Request Error")
        res = {'mgs': "error", 'error': "Request Error"}
    in_process = False
    return jsonify(res)

    # آدرس داخلی سرویس جدید پردازش تصویر که با Docker اجرا شده
    DOCKERIZED_IMAGE_API_URL = "http://localhost:8888/enhance" 

    @app.route("/new_image_enhancer/enhance/", methods=['POST'])
    def proxy_to_new_image_service():
        if 'file' not in request.files:
            return jsonify({'mgs': "error", 'error': "No selected file"}), 400
        
        client_file = request.files['file']
        if client_file.filename == '':
            return jsonify({'mgs': "error", 'error': "File name is empty"}), 400

        try:
            payload_data = {
                'saturation': request.form.get('saturation', '1.0'),
                'contrast': request.form.get('contrast', '1.0'),
                'sharpness': request.form.get('sharpness', '1.0'),
                'smart_enhance': str(request.form.get('smart_enhance', 'false')).lower()
            }

            files_to_send = {'file': (client_file.filename, client_file.stream, client_file.mimetype)}

            # از کتابخانه requests که در فایل API.py شما import شده، استفاده می کنیم
            # اگر import نشده، این خط را در بالای فایل اضافه کنید: import requests
            proxied_response = requests.post(
                DOCKERIZED_IMAGE_API_URL,
                data=payload_data,
                files=files_to_send,
                stream=True,
                timeout=300 
            )

            if proxied_response.status_code >= 400:
                try:
                    error_json = proxied_response.json()
                    return jsonify(error_json), proxied_response.status_code
                except ValueError: 
                    return jsonify({'mgs': "error", 'error': "Error from enhancement service", 'status_code': proxied_response.status_code}), proxied_response.status_code

            def generate_stream():
                for chunk in proxied_response.iter_content(chunk_size=8192): 
                    if chunk: 
                        yield chunk
            
            response_headers = {}
            for header_key, header_value in proxied_response.headers.items():
                if header_key.lower() in ['content-type', 'content-disposition']:
                    response_headers[header_key] = header_value
            
            return Response(generate_stream(), status=proxied_response.status_code, headers=response_headers)

        except requests.exceptions.RequestException as e:
            # مطمئن شوید که در بالای فایل API.py، عبارت import requests وجود داشته باشد
            print(f"Error connecting to enhancement service: {str(e)}")
            return jsonify({'mgs': "error", 'error': "Failed to connect to image enhancement service"}), 503 
        except Exception as e:
            print(f"Unexpected error in proxy: {str(e)}")
            return jsonify({'mgs': "error", 'error': "An unexpected error occurred while proxying the request"}), 500

if __name__ == "__main__":
    app.run(host="simage.boomilia.com", port=2056, ssl_context=('main/auth/cert.pem', 'main/auth/key.pem'))
