from json import loads
from os.path import exists
from sys import argv

from main.models import *

if len(argv) != 2:
    print("ERROR please enter posts_data.json path"), exit()

if not exists(argv[1]):
    print(f"ERROR {argv[1]} not exists!"), exit()

with open(argv[1], 'r') as file:
    dbs = loads(file.read())

oks, errs, skips = 0, 0, 0
print("INFO processing... please wait!")
available_types = [".png", ".jpg", ".jpeg", ".webp"]

for inputs in dbs:
    url = [i.split('/media/media/')[1] if 'media' in i else i for i in inputs.get("post_media")]
    tags = inputs.get("tags")
    session = Images().__ss__

    selected_image = session.query(Images).join(Info).where(Info.seo_id == inputs.get("seo_id"))
    if selected_image.first():
        errs += 1
    else:
        oks += 1
        img_info = Info(title=inputs.get("title"), seo_id=inputs.get("seo_id"))
        img_tags = []
        for tag in tags:
            selected_tag = Tags().query(Tags.name == tag)
            if exist := selected_tag.select.first():
                img_tags.append(exist)
            else:
                new_tag = Tags(name=tag)
                img_tags.append(new_tag)

        for u in url:
            if any(i for i in available_types if i in u):
                # بررسی وجود قبلی
                if not session.query(Images).filter_by(URL=u).first():
                    Images(URL=u, info=img_info, tags=img_tags, have_error=False).insert()
                else:
                    skips += 1
                    print(f"⚠️ تصویر تکراری رد شد: {u}")

print(f"✅ INFO: {oks} پست جدید، {errs} پست موجود قبلاً، {skips} تصویر تکراری رد شد.\nOK Done.")
