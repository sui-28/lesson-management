import os
import secrets
from datetime import datetime, timedelta, timezone
from flask import Flask, render_template, redirect, url_for, request, flash, jsonify, abort
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from sqlalchemy import create_engine, func
from sqlalchemy.orm import sessionmaker
from werkzeug.security import generate_password_hash, check_password_hash
from models import Base, User, Teacher, Student, Report, Notification

# ── アプリケーション設定 ──────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "instance", "juku.db")
DATABASE_URL = os.environ.get("DATABASE_URL",  f"sqlite:///{DB_PATH}")
# Render の PostgreSQL URL は "postgres://" で始まる場合があるため修正
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", secrets.token_hex(32))
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(hours=8)

# ── データベース ──────────────────────────────────────────────
engine = create_engine(DATABASE_URL, echo=False)
SessionLocal = sessionmaker(bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ── Flask-Login ───────────────────────────────────────────────
login_manager = LoginManager(app)
login_manager.login_view = "login"
login_manager.login_message = "ログインが必要です。"
login_manager.login_message_category = "warning"


@login_manager.user_loader
def load_user(user_id):
    db = SessionLocal()
    try:
        return db.get(User, int(user_id))
    finally:
        db.close()


# ── ヘルパー ──────────────────────────────────────────────────
def admin_required(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            abort(403)
        return f(*args, **kwargs)
    return decorated


def get_unread_notifications(db):
    if current_user.is_admin:
        return db.query(Notification).filter_by(is_read=False).order_by(
            Notification.created_at.desc()).all()
    return []


# ── 認証 ──────────────────────────────────────────────────────
@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        db = SessionLocal()
        try:
            user = db.query(User).filter_by(username=username).first()
            if user and check_password_hash(user.password_hash, password):
                login_user(user, remember=True)
                next_page = request.args.get("next")
                return redirect(next_page or url_for("dashboard"))
            flash("ユーザー名またはパスワードが正しくありません。", "danger")
        finally:
            db.close()
    return render_template("auth/login.html")


@app.route("/logout")
@login_required
def logout():
    logout_user()
    flash("ログアウトしました。", "info")
    return redirect(url_for("login"))


# ── ダッシュボード ────────────────────────────────────────────
@app.route("/")
@login_required
def dashboard():
    db = SessionLocal()
    try:
        notifications = get_unread_notifications(db)
        if current_user.is_admin:
            # 管理者: 全体統計
            total_teachers = db.query(func.count(Teacher.id)).scalar()
            total_students = db.query(func.count(Student.id)).scalar()

            # 月別授業回数（過去6ヶ月）
            monthly_stats = (
                db.query(
                    func.substr(Report.lesson_date, 1, 7).label("month"),
                    func.count(Report.id).label("cnt"),
                )
                .group_by(func.substr(Report.lesson_date, 1, 7))
                .order_by(func.substr(Report.lesson_date, 1, 7).desc())
                .limit(6)
                .all()
            )
            monthly_stats = list(reversed(monthly_stats))

            # メンティー別授業回数・残り回数
            student_stats = (
                db.query(Student, func.count(Report.id).label("cnt"))
                .outerjoin(Report, Report.student_id == Student.id)
                .group_by(Student.id)
                .order_by(Student.name)
                .all()
            )

            # 最近の報告書
            recent_reports = (
                db.query(Report)
                .order_by(Report.submitted_at.desc())
                .limit(5)
                .all()
            )

            return render_template(
                "dashboard_admin.html",
                total_teachers=total_teachers,
                total_students=total_students,
                monthly_stats=monthly_stats,
                student_stats=student_stats,
                recent_reports=recent_reports,
                notifications=notifications,
            )
        else:
            # 先生: 自分の統計
            teacher = current_user.teacher
            if not teacher:
                flash("先生情報が登録されていません。管理者に連絡してください。", "warning")
                return render_template("dashboard_teacher.html",
                                       teacher=None, notifications=notifications)

            my_reports_count = db.query(func.count(Report.id)).filter_by(
                teacher_id=teacher.id).scalar()
            my_students_count = len(teacher.students)

            # 自分の月別授業回数
            monthly = (
                db.query(
                    func.substr(Report.lesson_date, 1, 7).label("month"),
                    func.count(Report.id).label("cnt"),
                )
                .filter(Report.teacher_id == teacher.id)
                .group_by(func.substr(Report.lesson_date, 1, 7))
                .order_by(func.substr(Report.lesson_date, 1, 7).desc())
                .limit(6)
                .all()
            )
            monthly = list(reversed(monthly))

            # 自分の担当メンティー別授業回数・残り回数
            student_stats = (
                db.query(Student.name, func.count(Report.id).label("cnt"), Student.total_lessons)
                .outerjoin(Report, (Report.student_id == Student.id) & (Report.teacher_id == teacher.id))
                .filter(Student.id.in_([s.id for s in teacher.students]))
                .group_by(Student.id)
                .order_by(Student.name)
                .all()
            )

            recent_reports = (
                db.query(Report)
                .filter_by(teacher_id=teacher.id)
                .order_by(Report.submitted_at.desc())
                .limit(5)
                .all()
            )

            return render_template(
                "dashboard_teacher.html",
                teacher=teacher,
                my_reports_count=my_reports_count,
                my_students_count=my_students_count,
                monthly=monthly,
                student_stats=student_stats,
                recent_reports=recent_reports,
                notifications=notifications,
            )
    finally:
        db.close()


# ── 報告書 ────────────────────────────────────────────────────
@app.route("/reports")
@login_required
def report_list():
    db = SessionLocal()
    try:
        notifications = get_unread_notifications(db)
        query = db.query(Report).order_by(Report.lesson_date.desc(), Report.submitted_at.desc())
        if current_user.is_teacher:
            teacher = current_user.teacher
            if teacher:
                query = query.filter(Report.teacher_id == teacher.id)
            else:
                query = query.filter(Report.id == -1)  # 空結果

        # 検索フィルタ
        teacher_id = request.args.get("teacher_id")
        student_id = request.args.get("student_id")
        date_from = request.args.get("date_from")
        date_to = request.args.get("date_to")

        if teacher_id and current_user.is_admin:
            query = query.filter(Report.teacher_id == int(teacher_id))
        if student_id:
            query = query.filter(Report.student_id == int(student_id))
        if date_from:
            query = query.filter(Report.lesson_date >= date_from)
        if date_to:
            query = query.filter(Report.lesson_date <= date_to)

        reports = query.all()
        teachers = db.query(Teacher).order_by(Teacher.name).all() if current_user.is_admin else []
        students = db.query(Student).order_by(Student.name).all()

        return render_template("reports/list.html",
                               reports=reports,
                               teachers=teachers,
                               students=students,
                               notifications=notifications)
    finally:
        db.close()


@app.route("/reports/new", methods=["GET", "POST"])
@login_required
def report_new():
    db = SessionLocal()
    try:
        notifications = get_unread_notifications(db)
        if request.method == "POST":
            teacher_id = request.form.get("teacher_id")
            student_id = request.form.get("student_id")
            lesson_date = request.form.get("lesson_date", "").strip()
            lesson_duration = request.form.get("lesson_duration", "").strip()
            content = request.form.get("content", "").strip()
            next_plan = request.form.get("next_plan", "").strip()

            errors = []
            if not lesson_date:
                errors.append("授業実施日は必須です。")
            if not lesson_duration:
                errors.append("授業時間は必須です。")
            if not student_id:
                errors.append("生徒名は必須です。")
            if not teacher_id:
                errors.append("担当先生は必須です。")

            # 先生は自分以外の teacher_id を指定できない
            if current_user.is_teacher:
                teacher = current_user.teacher
                if not teacher or str(teacher.id) != str(teacher_id):
                    errors.append("担当先生を変更する権限がありません。")
                    teacher_id = teacher.id if teacher else None

            if errors:
                for e in errors:
                    flash(e, "danger")
            else:
                report = Report(
                    teacher_id=int(teacher_id),
                    student_id=int(student_id),
                    lesson_date=lesson_date,
                    lesson_duration=lesson_duration,
                    content=content or None,
                    next_plan=next_plan or None,
                )
                db.add(report)
                db.commit()
                flash("報告書を提出しました。", "success")
                return redirect(url_for("report_list"))

        teachers = db.query(Teacher).order_by(Teacher.name).all()
        students = db.query(Student).order_by(Student.name).all()
        current_teacher = current_user.teacher if current_user.is_teacher else None

        return render_template("reports/new.html",
                               teachers=teachers,
                               students=students,
                               current_teacher=current_teacher,
                               notifications=notifications)
    finally:
        db.close()


@app.route("/reports/<int:report_id>")
@login_required
def report_detail(report_id):
    db = SessionLocal()
    try:
        notifications = get_unread_notifications(db)
        report = db.get(Report, report_id)
        if not report:
            abort(404)
        # 先生は自分の報告書のみ
        if current_user.is_teacher:
            teacher = current_user.teacher
            if not teacher or report.teacher_id != teacher.id:
                abort(403)
        return render_template("reports/detail.html", report=report,
                               notifications=notifications)
    finally:
        db.close()


@app.route("/reports/<int:report_id>/edit", methods=["GET", "POST"])
@login_required
def report_edit(report_id):
    db = SessionLocal()
    try:
        notifications = get_unread_notifications(db)
        report = db.get(Report, report_id)
        if not report:
            abort(404)
        if current_user.is_teacher:
            teacher = current_user.teacher
            if not teacher or report.teacher_id != teacher.id:
                abort(403)

        if request.method == "POST":
            lesson_date = request.form.get("lesson_date", "").strip()
            lesson_duration = request.form.get("lesson_duration", "").strip()
            student_id = request.form.get("student_id")
            content = request.form.get("content", "").strip()
            next_plan = request.form.get("next_plan", "").strip()

            errors = []
            if not lesson_date:
                errors.append("授業実施日は必須です。")
            if not lesson_duration:
                errors.append("授業時間は必須です。")
            if not student_id:
                errors.append("生徒名は必須です。")

            if errors:
                for e in errors:
                    flash(e, "danger")
            else:
                report.lesson_date = lesson_date
                report.lesson_duration = lesson_duration
                report.student_id = int(student_id)
                report.content = content or None
                report.next_plan = next_plan or None
                report.updated_at = datetime.now(timezone.utc)
                db.commit()
                flash("報告書を更新しました。", "success")
                return redirect(url_for("report_detail", report_id=report.id))

        teachers = db.query(Teacher).order_by(Teacher.name).all()
        students = db.query(Student).order_by(Student.name).all()
        return render_template("reports/edit.html",
                               report=report,
                               teachers=teachers,
                               students=students,
                               notifications=notifications)
    finally:
        db.close()


# ── API: 生徒名サジェスト ─────────────────────────────────────
@app.route("/api/students")
@login_required
def api_students():
    teacher_id = request.args.get("teacher_id", type=int)
    q = request.args.get("q", "").strip()
    db = SessionLocal()
    try:
        if teacher_id:
            teacher = db.get(Teacher, teacher_id)
            assigned = teacher.students if teacher else []
            assigned_ids = {s.id for s in assigned}
            all_students = db.query(Student).order_by(Student.name).all()

            result = []
            # 担当生徒を優先
            for s in assigned:
                if not q or q in s.name:
                    result.append({"id": s.id, "name": s.name, "assigned": True})
            # 担当外
            for s in all_students:
                if s.id not in assigned_ids:
                    if not q or q in s.name:
                        result.append({"id": s.id, "name": s.name, "assigned": False})
        else:
            students = db.query(Student).order_by(Student.name).all()
            result = [{"id": s.id, "name": s.name, "assigned": None}
                      for s in students if not q or q in s.name]

        return jsonify(result[:30])
    finally:
        db.close()


# ── API: 通知を既読 ───────────────────────────────────────────
@app.route("/api/notifications/<int:nid>/read", methods=["POST"])
@login_required
@admin_required
def mark_notification_read(nid):
    db = SessionLocal()
    try:
        n = db.get(Notification, nid)
        if n:
            n.is_read = True
            db.commit()
        return jsonify({"ok": True})
    finally:
        db.close()


# ── 管理者: 先生管理 ──────────────────────────────────────────
@app.route("/admin/teachers")
@login_required
@admin_required
def admin_teachers():
    db = SessionLocal()
    try:
        notifications = get_unread_notifications(db)
        teachers = db.query(Teacher).order_by(Teacher.name).all()
        users = db.query(User).filter_by(role="teacher").order_by(User.username).all()
        return render_template("admin/teachers.html",
                               teachers=teachers, users=users,
                               notifications=notifications)
    finally:
        db.close()


@app.route("/admin/teachers/new", methods=["POST"])
@login_required
@admin_required
def admin_teacher_new():
    db = SessionLocal()
    try:
        name = request.form.get("name", "").strip()
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()

        if not name or not username or not password:
            flash("名前・ユーザー名・パスワードはすべて必須です。", "danger")
            return redirect(url_for("admin_teachers"))

        existing = db.query(User).filter_by(username=username).first()
        if existing:
            flash(f"ユーザー名「{username}」はすでに使用されています。", "danger")
            return redirect(url_for("admin_teachers"))

        user = User(
            username=username,
            password_hash=generate_password_hash(password),
            role="teacher",
        )
        db.add(user)
        db.flush()

        teacher = Teacher(name=name, user_id=user.id)
        db.add(teacher)
        db.commit()
        flash(f"先生「{name}」を登録しました。", "success")
    finally:
        db.close()
    return redirect(url_for("admin_teachers"))


@app.route("/admin/teachers/<int:tid>/delete", methods=["POST"])
@login_required
@admin_required
def admin_teacher_delete(tid):
    db = SessionLocal()
    try:
        teacher = db.get(Teacher, tid)
        if teacher:
            user = teacher.user
            db.delete(teacher)
            if user:
                db.delete(user)
            db.commit()
            flash("先生を削除しました。", "success")
    finally:
        db.close()
    return redirect(url_for("admin_teachers"))


# ── 管理者: 生徒管理 ──────────────────────────────────────────
@app.route("/admin/students")
@login_required
@admin_required
def admin_students():
    db = SessionLocal()
    try:
        notifications = get_unread_notifications(db)
        students = db.query(Student).order_by(Student.name).all()
        return render_template("admin/students.html", students=students,
                               notifications=notifications)
    finally:
        db.close()


@app.route("/admin/students/new", methods=["POST"])
@login_required
@admin_required
def admin_student_new():
    db = SessionLocal()
    try:
        name = request.form.get("name", "").strip()
        if not name:
            flash("生徒名は必須です。", "danger")
            return redirect(url_for("admin_students"))
        student = Student(name=name)
        db.add(student)
        db.commit()
        flash(f"生徒「{name}」を登録しました。", "success")
    finally:
        db.close()
    return redirect(url_for("admin_students"))


@app.route("/admin/students/<int:sid>/delete", methods=["POST"])
@login_required
@admin_required
def admin_student_delete(sid):
    db = SessionLocal()
    try:
        student = db.get(Student, sid)
        if student:
            db.delete(student)
            db.commit()
            flash("メンティーを削除しました。", "success")
    finally:
        db.close()
    return redirect(url_for("admin_students"))


@app.route("/admin/students/<int:sid>/set_total", methods=["POST"])
@login_required
@admin_required
def admin_student_set_total(sid):
    """メンティーの総授業回数を設定"""
    db = SessionLocal()
    try:
        student = db.get(Student, sid)
        if student:
            val = request.form.get("total_lessons", "").strip()
            student.total_lessons = int(val) if val.isdigit() else None
            db.commit()
            flash(f"「{student.name}」の総授業回数を更新しました。", "success")
    finally:
        db.close()
    return redirect(url_for("admin_students"))


# ── 管理者: CSVインポート ─────────────────────────────────────
@app.route("/admin/import", methods=["GET", "POST"])
@login_required
@admin_required
def admin_import():
    """メンター・メンティー対応表CSVをインポート"""
    notifications = []
    if request.method == "POST":
        f = request.files.get("csv_file")
        if not f or not f.filename.endswith(".csv"):
            flash("CSVファイルを選択してください。", "danger")
            return redirect(url_for("admin_import"))

        import csv, io
        content = f.read().decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(content))

        db = SessionLocal()
        try:
            created_mentors = created_mentees = created_assignments = 0
            for row in reader:
                mentor_name = (row.get("メンター名") or row.get("mentor") or "").strip()
                mentee_name = (row.get("メンティー名") or row.get("mentee") or "").strip()
                if not mentor_name or not mentee_name:
                    continue

                # メンター取得 or 作成
                teacher = db.query(Teacher).filter_by(name=mentor_name).first()
                if not teacher:
                    teacher = Teacher(name=mentor_name)
                    db.add(teacher)
                    db.flush()
                    created_mentors += 1

                # メンティー取得 or 作成
                student = db.query(Student).filter_by(name=mentee_name).first()
                if not student:
                    student = Student(name=mentee_name)
                    db.add(student)
                    db.flush()
                    created_mentees += 1

                # 担当割当
                if student not in teacher.students:
                    teacher.students.append(student)
                    created_assignments += 1

            db.commit()
            flash(
                f"インポート完了: メンター {created_mentors}名追加、"
                f"メンティー {created_mentees}名追加、"
                f"担当 {created_assignments}件追加。",
                "success"
            )
        except Exception as e:
            db.rollback()
            flash(f"インポートエラー: {e}", "danger")
        finally:
            db.close()

        return redirect(url_for("admin_import"))

    db = SessionLocal()
    try:
        notifications = get_unread_notifications(db)
    finally:
        db.close()
    return render_template("admin/import.html", notifications=notifications)


# ── 管理者: 担当割当管理 ──────────────────────────────────────
@app.route("/admin/assignments")
@login_required
@admin_required
def admin_assignments():
    db = SessionLocal()
    try:
        notifications = get_unread_notifications(db)
        teachers = db.query(Teacher).order_by(Teacher.name).all()
        students = db.query(Student).order_by(Student.name).all()
        return render_template("admin/assignments.html",
                               teachers=teachers, students=students,
                               notifications=notifications)
    finally:
        db.close()


@app.route("/admin/assignments/add", methods=["POST"])
@login_required
@admin_required
def admin_assignment_add():
    db = SessionLocal()
    try:
        teacher_id = request.form.get("teacher_id", type=int)
        student_id = request.form.get("student_id", type=int)
        teacher = db.get(Teacher, teacher_id)
        student = db.get(Student, student_id)
        if teacher and student:
            if student not in teacher.students:
                teacher.students.append(student)
                db.commit()
                flash(f"「{teacher.name}」と「{student.name}」の担当を登録しました。", "success")
            else:
                flash("その担当関係はすでに登録されています。", "info")
        else:
            flash("先生または生徒が見つかりません。", "danger")
    finally:
        db.close()
    return redirect(url_for("admin_assignments"))


@app.route("/admin/assignments/remove", methods=["POST"])
@login_required
@admin_required
def admin_assignment_remove():
    db = SessionLocal()
    try:
        teacher_id = request.form.get("teacher_id", type=int)
        student_id = request.form.get("student_id", type=int)
        teacher = db.get(Teacher, teacher_id)
        student = db.get(Student, student_id)
        if teacher and student and student in teacher.students:
            teacher.students.remove(student)
            db.commit()
            flash("担当を解除しました。", "success")
    finally:
        db.close()
    return redirect(url_for("admin_assignments"))


# ── 管理者: ユーザー管理（管理者アカウント追加）───────────────
@app.route("/admin/users")
@login_required
@admin_required
def admin_users():
    db = SessionLocal()
    try:
        notifications = get_unread_notifications(db)
        users = db.query(User).order_by(User.role, User.username).all()
        return render_template("admin/users.html", users=users,
                               notifications=notifications)
    finally:
        db.close()


@app.route("/admin/users/new", methods=["POST"])
@login_required
@admin_required
def admin_user_new():
    db = SessionLocal()
    try:
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()
        role = request.form.get("role", "admin")
        if role not in ("admin", "teacher"):
            role = "admin"
        if not username or not password:
            flash("ユーザー名とパスワードは必須です。", "danger")
            return redirect(url_for("admin_users"))
        existing = db.query(User).filter_by(username=username).first()
        if existing:
            flash("そのユーザー名はすでに使用されています。", "danger")
            return redirect(url_for("admin_users"))
        user = User(username=username,
                    password_hash=generate_password_hash(password),
                    role=role)
        db.add(user)
        db.commit()
        flash(f"ユーザー「{username}」を追加しました。", "success")
    finally:
        db.close()
    return redirect(url_for("admin_users"))


@app.route("/admin/users/<int:uid>/delete", methods=["POST"])
@login_required
@admin_required
def admin_user_delete(uid):
    if uid == current_user.id:
        flash("自分自身は削除できません。", "danger")
        return redirect(url_for("admin_users"))
    db = SessionLocal()
    try:
        user = db.get(User, uid)
        if user:
            db.delete(user)
            db.commit()
            flash("ユーザーを削除しました。", "success")
    finally:
        db.close()
    return redirect(url_for("admin_users"))


# ── 管理者: 未提出アラート確認 ────────────────────────────────
@app.route("/admin/alerts")
@login_required
@admin_required
def admin_alerts():
    db = SessionLocal()
    try:
        notifications = get_unread_notifications(db)
        # 直近30日の授業報告書から未提出チェック（簡易: 管理者手動実行）
        # ここでは通知一覧を表示
        all_notifications = db.query(Notification).order_by(
            Notification.created_at.desc()).limit(100).all()
        return render_template("admin/alerts.html",
                               all_notifications=all_notifications,
                               notifications=notifications)
    finally:
        db.close()


@app.route("/admin/alerts/check", methods=["POST"])
@login_required
@admin_required
def admin_alerts_check():
    """未提出アラートを手動チェック（管理者が実行）"""
    db = SessionLocal()
    try:
        threshold_days = int(request.form.get("threshold_days", 3))
        cutoff = (datetime.now(timezone.utc) - timedelta(days=threshold_days)).date()

        # 最近作成された報告書を確認し、lesson_date が古いのに未提出な先生を検出
        # 簡易実装: すべての先生×全生徒ペアについて、cutoff以前に報告書がない組み合わせを検出
        # 実際にはスケジューラ等で自動化するのが望ましい
        teachers = db.query(Teacher).all()
        new_alerts = 0
        for teacher in teachers:
            for student in teacher.students:
                latest = (
                    db.query(Report)
                    .filter_by(teacher_id=teacher.id, student_id=student.id)
                    .order_by(Report.lesson_date.desc())
                    .first()
                )
                if latest:
                    from datetime import date
                    latest_date = date.fromisoformat(latest.lesson_date)
                    days_since = (date.today() - latest_date).days
                    if days_since > threshold_days * 7:  # 週単位で授業があると仮定
                        msg = (f"⚠️ 未提出アラート: {teacher.name} → {student.name} "
                               f"（最終報告: {latest.lesson_date}, {days_since}日経過）")
                        exists = db.query(Notification).filter(
                            Notification.message == msg,
                            Notification.is_read == False
                        ).first()
                        if not exists:
                            db.add(Notification(message=msg))
                            new_alerts += 1

        db.commit()
        flash(f"アラートチェック完了。{new_alerts}件の新規アラートを生成しました。", "success")
    finally:
        db.close()
    return redirect(url_for("admin_alerts"))


# ── 初期データ投入 ────────────────────────────────────────────
def init_db():
    """DBテーブル作成と初期管理者アカウント生成"""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    Base.metadata.create_all(engine)
    db = SessionLocal()
    try:
        existing_admin = db.query(User).filter_by(role="admin").first()
        if not existing_admin:
            admin = User(
                username="admin",
                password_hash=generate_password_hash("admin1234"),
                role="admin",
            )
            db.add(admin)
            db.commit()
            print("初期管理者アカウントを作成しました: admin / admin1234")
    finally:
        db.close()


# 起動時に自動でDB初期化（gunicorn経由でも動作）
try:
    init_db()
except Exception as e:
    print(f"[WARNING] DB初期化エラー: {e}")

if __name__ == "__main__":
    app.run(debug=True, port=5050)
