from typing import List, Optional

from sqlalchemy import (
    create_engine, ForeignKey, String, JSON
)
from sqlalchemy.orm import sessionmaker, Mapped, mapped_column, relationship, scoped_session

try:
    from main.ORM import Base
except ImportError:
    from ORM import Base

engine = create_engine(
    f"mysql://root:Y^*89ytrey@localhost/image_engine?charset=utf8mb4"
)

Base.__session__ = sessionmaker(bind=engine)
Base.__ss__ = scoped_session(Base.__session__)


class Post(Base):
    __tablename__ = "post"
    id: Mapped[int] = mapped_column(primary_key=True)
    tag_id: Mapped[int] = mapped_column(ForeignKey('tags.id', onupdate='CASCADE'))
    image_id: Mapped[int] = mapped_column(ForeignKey('images.id', onupdate='CASCADE'))


class Images(Base):
    __tablename__ = 'images'
    id: Mapped[int] = mapped_column(primary_key=True)
    URL: Mapped[str] = mapped_column(String(1024), unique=True, index=True)

    processed: Mapped[bool] = mapped_column(default=False)
    have_error: Mapped[bool] = mapped_column(default=False)
    stack_num: Mapped[int] = mapped_column(nullable=True)
    data: Mapped[Optional[dict | list]] = mapped_column(type_=JSON, default={})

    info_id: Mapped[int] = mapped_column(ForeignKey('info.id', onupdate='CASCADE'))
    tags: Mapped[List["Tags"]] = relationship("Tags", secondary='post', back_populates="images")


class Tags(Base):
    __tablename__ = 'tags'
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255))

    images: Mapped[List["Images"]] = relationship("Images", secondary='post', back_populates="tags")


class Info(Base):
    __tablename__ = 'info'
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(255), index=True)
    seo_id: Mapped[str] = mapped_column(String(300))
    image: Mapped[List["Images"]] = relationship("Images", backref="info")


if __name__ == '__main__':
    if input("Do you want to Drop All Data? (Y/N): ").lower() in ['y', 'yes']:
        Base.metadata.drop_all(engine)
    print('OK')

    # tags = ["3d", "gallery"]
    # for tag in tags:
    #     info = Info(title="salam", seo_id="salam-123")
    #     image = Images(URL='123', info=info).insert()
    #     for i in range(2):
    #         status = Tags().where(Tags.name == tag).first()
    #         if status:
    #             Post(image_id=image.filter().first().id, tag_id=status.id).insert()
    #             break
    #         else:
    #             Tags(name=tag).insert()
    #
    # print(Images(id=1).get_tags().all())
    # print(Images(id=1).get_attr("URL"))
Base.metadata.create_all(engine)
