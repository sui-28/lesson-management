from flask_login import UserMixin
from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text, ForeignKey, Table
from sqlalchemy.orm import relationship, DeclarativeBase
from datetime import datetime, timezone


class Base(DeclarativeBase):
    pass


# 先生と生徒の多対多中間テーブル
assignment_table = Table(
    "assignment",
    Base.metadata,
    Column("teacher_id", Integer, ForeignKey("teacher.id"), primary_key=True),
    Column("student_id", Integer, ForeignKey("student.id"), primary_key=True),
)


class User(UserMixin, Base):
    """ログインユーザー（管理者・先生共通）"""
    __tablename__ = "user"

    id = Column(Integer, primary_key=True)
    username = Column(String(100), unique=True, nullable=False)
    password_hash = Column(String(256), nullable=False)
    role = Column(String(20), nullable=False)  # "admin" or "teacher"
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    # 先生ロールの場合のみ関連
    teacher = relationship("Teacher", back_populates="user", uselist=False, lazy="selectin")

    @property
    def is_admin(self):
        return self.role == "admin"

    @property
    def is_teacher(self):
        return self.role == "teacher"


class Teacher(Base):
    """先生マスタ"""
    __tablename__ = "teacher"

    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    user_id = Column(Integer, ForeignKey("user.id"), nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    user = relationship("User", back_populates="teacher")
    students = relationship("Student", secondary=assignment_table, back_populates="teachers", lazy="selectin")
    reports = relationship("Report", back_populates="teacher", lazy="selectin")


class Student(Base):
    """生徒マスタ"""
    __tablename__ = "student"

    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    teachers = relationship("Teacher", secondary=assignment_table, back_populates="students", lazy="selectin")
    reports = relationship("Report", back_populates="student", lazy="selectin")


class Report(Base):
    """授業報告書"""
    __tablename__ = "report"

    id = Column(Integer, primary_key=True)
    teacher_id = Column(Integer, ForeignKey("teacher.id"), nullable=False)
    student_id = Column(Integer, ForeignKey("student.id"), nullable=False)
    lesson_date = Column(String(10), nullable=False)   # YYYY-MM-DD
    lesson_duration = Column(String(50), nullable=False)  # 例: "60分", "90分"
    content = Column(Text, nullable=True)
    next_plan = Column(Text, nullable=True)
    submitted_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))

    teacher = relationship("Teacher", back_populates="reports", lazy="selectin")
    student = relationship("Student", back_populates="reports", lazy="selectin")


class Notification(Base):
    """システム内通知（未提出アラート等）"""
    __tablename__ = "notification"

    id = Column(Integer, primary_key=True)
    message = Column(Text, nullable=False)
    is_read = Column(Boolean, default=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
