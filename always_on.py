from os import system
from time import sleep

from screenutils import list_screens
from datetime import datetime

sleep(60), print("Services Always ONLINE.")
services = {
    "image_search_engine": "runner",
    "update_images_service": "service",
    "webservice": "API",
}

while True:
    session_names = [s.name for s in list_screens()]
    dif_res = set(list(services.keys())).difference(set(session_names))
    if dif_res:
        with open("log.txt", "a") as log_file:
            log_file.write(f"{datetime.now()}  - {dif_res}\n")
        system("cd /home/morteza/services && /usr/bin/python3 reboot_services.py")
        sleep(30)
    sleep(1)
