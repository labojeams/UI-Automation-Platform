"""
SQLAlchemy 引擎 / Session / Base 与初始化函数。

- 使用 SQLite 文件库，路径来自 config.DB_URL
- check_same_thread=False 以支持 Flask + 后台运行线程共享连接
- scoped_session 让多线程下每个线程拿到独立 Session
"""
from contextlib import contextmanager

from sqlalchemy import create_engine, event
from sqlalchemy.orm import declarative_base, sessionmaker, scoped_session

from ..config import DB_URL

# SQLite 多线程支持
engine = create_engine(
    DB_URL,
    echo=False,
    future=True,
    connect_args={"check_same_thread": False},
)


# 启用外键约束（SQLite 默认关闭）
@event.listens_for(engine, "connect")
def _enable_sqlite_fk(dbapi_conn, _):
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA foreign_keys=ON;")
    cur.close()


SessionFactory = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
Session = scoped_session(SessionFactory)

Base = declarative_base()


def init_db():
    """启动时调用：建表（已存在则跳过）。"""
    # 必须先 import entities 让模型注册到 Base.metadata
    from . import entities  # noqa: F401
    Base.metadata.create_all(bind=engine)


@contextmanager
def session_scope():
    """事务级 Session 上下文管理器。"""
    s = Session()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        Session.remove()