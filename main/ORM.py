__all__ = [
    "Base",
]

from sqlalchemy.orm import DeclarativeBase, state, Session, scoped_session


class Base(DeclarativeBase):
    __session__: Session = ...
    __ss__: scoped_session = ...

    def create(self, action, result: bool = True):
        with self.__ss__() as connection:
            connection.commit()
        return action if result else self

    @property
    def c(self):
        return self.__class__.c

    @property
    def __class_kwargs__(self):
        return dict(filter(lambda item: not isinstance(item[1], state.InstanceState), self.__table__.c.items()))

    def __repr__(self) -> str:
        return f"{self.__class__}"

    #            f"({', '.join([f'{key}={self.__getattribute__(key)!r}' for key in self.__annotations__])})"

    def insert(self):
        return self.create(self.__ss__.add(self), False)

    def filter(self, **filters):
        return self.__ss__.query(self.__class__).filter_by(
            **(filters or self.__class_kwargs__)
        )

    def where(self, where):
        return self.__ss__.query(self.__class__).where(where)

    def query(self, *where, **filters):
        return query_design(self, *where, **filters)


class query_design:
    def __init__(self, base: Base, *where, **filters):
        self.base, self.where, self.filters = base, where, filters
        self.element = (len(where) == 1 and isinstance(where[0], base.__class__) and where[0]) or \
                       filters.get('element') and filters.get('element')
        if not self.element:
            if where != ():
                self.element = base.where(*where)
            elif filters != {}:
                print(base.__class_kwargs__)
                self.element = base.filter(**(self.filters or base.__class_kwargs__))

    def update(self, **update):
        return self.base.create(self.element.update(values=update))

    @property
    def delete(self):
        return self.base.create(self.element.delete())

    @property
    def select(self):
        return self.element
