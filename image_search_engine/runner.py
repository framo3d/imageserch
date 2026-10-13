from glob import glob
from os import system, getpid
from threading import Thread

import psutil

proc_exists = (lambda name: [p for p in psutil.process_iter() if p.name() in name])
file_name = "image_search_engine.engine"

for proc in proc_exists(['python3']):
    try:
        run_c = proc.cmdline()
        if len(run_c) >= 2:
            if ("runner.py" in run_c[1] or file_name in run_c[1]) and proc.pid != getpid():
                proc.kill()
    except psutil.NoSuchProcess:
        pass

for stack_number in range(len(glob("main/stacks/*"))):
    Thread(target=system, args=(f"python3 -m {file_name} -s {stack_number}",)).start()
    print(f"stack_{stack_number}.npz is running on {1970 + stack_number} PORT.")
