""":types: of status
insert = have-error: 0, processed: 0
deactive = have-error: 1, processed: 1
active = have-error: 0, processed: 1
delete = remove post from database
"""

import urllib.request
from glob import glob
from os import path, listdir

import cv2
import numpy as np
from time import sleep

from main.colordescriptor import ColorDescriptor
from main.models import Images

BASE62 = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
BASE_URL = 'http://boomilia.com/media/media/'
def_stacks_path = r"main/stacks"
cd = ColorDescriptor((8, 12, 3))
limits = {
    "each_stacks": 10_000,
}


def read_stack(name):
    with np.load(name, allow_pickle=True) as sel_stack:
        stack = list(sel_stack['arr_0'].T.tolist().items())
    return stack


def save_stack(name, stack):
    return np.savez(name, np.array(stack, dtype=np.object_))


def download_and_describe(url):
    return cd.describe(
        cv2.imdecode(
            np.asarray(
                bytearray(
                    urllib.request.urlopen(BASE_URL + url, timeout=5).read()
                ), dtype=np.uint8
            ), -1
        )
    )


def get_stack_names(file_path, step):
    try:
        if not glob(file_path):
            save_stack(path.join(file_path.replace("*.npz", ""), "stack0.npz"), dict())
        return sorted(glob(file_path), key=lambda i: int(path.basename(i).split(f"stack")[1].split(".")[0]))[step]
    except:
        print(f"ERROR Please replace stacks path, cause it is incorrect! {def_stacks_path}")


def encode(num, alphabet=BASE62):
    if num == 0:
        return alphabet[0]
    arr = []
    base = len(alphabet)
    while num:
        num, rem = divmod(num, base)
        arr.append(alphabet[rem])
    return ''.join(arr[::-1])


while True:
    last_stack_name = get_stack_names(path.join(def_stacks_path, "*.npz"), -1)
    last_stack_number = int(path.basename(last_stack_name).split('stack')[1].split('.')[0])
    last_stack = read_stack(last_stack_name)
    last_stack_free_space = max(0, limits["each_stacks"] - len(last_stack))  # 0 or n>0
    print(
        f"OK stack details received!\t"
        f"Name: {last_stack_name}, "
        f"Number: {last_stack_number}, "
        f"N-Free: {last_stack_free_space}."
    )
    if last_stack_free_space > 0:
        while True:
            images = Images().filter(processed=False, have_error=False).limit(last_stack_free_space).all()
            if len(images) < 1:
                print("Not enough images, wait a few seconds..."), sleep(600)
            else:
                break
        print(f"{len(images)} image(P=0, H=0) received.")
        ok_ids, err_ids = [], []
        for img in images:
            try:
                last_stack += [(encode(img.id), np.array(download_and_describe(img.URL)))]
                ok_ids.append(img.id)
            except:
                err_ids.append(img.id)
        # input()
        save_stack(last_stack_name, dict(last_stack))
        print(f"stack_{last_stack_number} Updated !")

        with Images().__ss__() as session:
            session.query(Images).where(Images.id.in_(ok_ids)).update(
                values={
                    'processed': True,
                    'have_error': False,
                    'stack_num': last_stack_number,
                }
            )
            session.query(Images).where(Images.id.in_(err_ids)).update(
                values={
                    'processed': True,
                    'have_error': True,
                    'stack_num': last_stack_number,
                }
            )
            session.commit()

        print(f"OK saved! stack_number: {last_stack_number}, oks: {len(ok_ids)}, errs: {len(err_ids)}")
    else:
        new_stack_dst = path.join(def_stacks_path, f"stack{last_stack_number + 1}.npz")
        print(f"stack_{last_stack_number} IS FULL!")
        save_stack(new_stack_dst, {}), print(f"INFO new stack created! with name: {new_stack_dst}")

    print("sleep for 5 min..."), sleep(60 * 5)
