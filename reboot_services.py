import os
    
from screenutils import list_screens, Screen

session_names = [s.name for s in list_screens()]

services = {
    "image_search_engine": "runner",
    "update_images_service": "service",
    "webservice": "API",
}

for service, main in services.items():
    if service in session_names:
        Screen(service).kill()

    service_session = Screen(service, initialize=True)
    if service_session.exists:
      service_session.send_commands(f"/usr/bin/python3 -m {service}.{main}")
    else:
       os.system(f"screen -S {service} -dm /usr/bin/python3 -m {service}.{main}")