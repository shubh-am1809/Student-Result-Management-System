from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    session,
    send_file,
)
import sqlite3
import os
from io import BytesIO

from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

app = Flask(__name__)
app.secret_key = "any-secret-key"
DATABASE = "db.sqlite3"


#  DB CONNECTION 
def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn


# INIT DB
def init_db():
    conn = get_db()
    cur = conn.cursor()

    # Users table (Admin / Teacher)
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE,
            password TEXT,
            role TEXT
        )
        """
    )

    # Students table (with DOB)
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS students (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            roll_no TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            class_name TEXT NOT NULL,
            dob TEXT NOT NULL
        )
        """
    )

    # Results table (marks + max_marks)
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL,
            subject TEXT NOT NULL,
            marks INTEGER NOT NULL,
            max_marks INTEGER NOT NULL,
            FOREIGN KEY(student_id) REFERENCES students(id)
        )
        """
    )

    # Default admin & teacher (only if no users yet)
    cur.execute("SELECT COUNT(*) AS c FROM users")
    row = cur.fetchone()
    if row["c"] == 0:
        cur.execute(
            "INSERT INTO users(username, password, role) VALUES (?, ?, ?)",
            ("admin", "admin123", "admin"),
        )
        cur.execute(
            "INSERT INTO users(username, password, role) VALUES (?, ?, ?)",
            ("teacher", "teacher123", "teacher"),
        )
        conn.commit()

    conn.commit()
    conn.close()


# AUTH DECORATORS
def login_required(f):
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            flash("Please login first!", "error")
            return redirect(url_for("login"))
        return f(*args, **kwargs)

    wrapper.__name__ = f.__name__
    return wrapper


def admin_required(f):
    def wrapper(*args, **kwargs):
        if session.get("role") != "admin":
            flash("Admin only access!", "error")
            return redirect(url_for("index"))
        return f(*args, **kwargs)

    wrapper.__name__ = f.__name__
    return wrapper


def staff_required(f):
    # Admin or Teacher
    def wrapper(*args, **kwargs):
        if session.get("role") not in ("admin", "teacher"):
            flash("Only staff (admin/teacher) can access this page!", "error")
            return redirect(url_for("index"))
        return f(*args, **kwargs)

    wrapper.__name__ = f.__name__
    return wrapper


# STAFF LOGIN (ADMIN/TEACHER) 
@app.route("/login", methods=["GET", "POST"])
def login():
    if "user_id" in session and session.get("role") in ("admin", "teacher"):
        return redirect(url_for("index"))

    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]

        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM users WHERE username=? AND password=?",
            (username, password),
        )
        user = cur.fetchone()
        conn.close()

        if user:
            session["user_id"] = user["id"]
            session["username"] = user["username"]
            session["role"] = user["role"]
            flash(f"Welcome {user['username']}!", "success")
            return redirect(url_for("index"))
        else:
            flash("Invalid staff login!", "error")

    return render_template("login.html")


# STUDENT LOGIN 
@app.route("/student/login", methods=["GET", "POST"])
def student_login():
    if "user_id" in session and session.get("role") == "student":
        return redirect(url_for("student_dashboard"))

    if request.method == "POST":
        roll_no = request.form["roll_no"]
        dob = request.form["dob"]  # YYYY-MM-DD

        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM students WHERE roll_no=? AND dob=?",
            (roll_no, dob),
        )
        student = cur.fetchone()
        conn.close()

        if student:
            session["user_id"] = student["id"]
            session["username"] = student["name"]
            session["role"] = "student"
            session["student_id"] = student["id"]
            session["student_roll_no"] = student["roll_no"]
            flash("Student login successful!", "success")
            return redirect(url_for("student_dashboard"))
        else:
            flash("Invalid Roll No or Date of Birth!", "error")

    return render_template("student_login.html")


#  LOGOUT 
@app.route("/logout")
def logout():
    session.clear()
    flash("Logged out!", "success")
    return redirect(url_for("login"))


# HOME 
@app.route("/")
@login_required
def index():
    return render_template("index.html")


# ADMIN DASHBOARD 
@app.route("/admin/dashboard")
@login_required
@admin_required
def admin_dashboard():
    conn = get_db()
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*) AS c FROM students")
    total_students = cur.fetchone()["c"]

    cur.execute("SELECT COUNT(*) AS c FROM results")
    total_results = cur.fetchone()["c"]

    # overall obtained & max for percentage
    cur.execute("SELECT SUM(marks) AS total_obt, SUM(max_marks) AS total_max FROM results")
    row = cur.fetchone()
    total_obt = row["total_obt"] if row["total_obt"] is not None else 0
    total_max = row["total_max"] if row["total_max"] is not None else 0
    avg_percentage = (total_obt / total_max * 100) if total_max > 0 else 0

    cur.execute("SELECT COUNT(DISTINCT subject) AS c FROM results")
    subjects_count = cur.fetchone()["c"]

    cur.execute(
        """
        SELECT r.id, r.subject, r.marks, r.max_marks,
               s.roll_no, s.name, s.class_name
        FROM results r
        JOIN students s ON r.student_id = s.id
        ORDER BY r.id DESC
        LIMIT 10
        """
    )
    recent_results = cur.fetchall()

    conn.close()

    return render_template(
        "admin_dashboard.html",
        total_students=total_students,
        total_results=total_results,
        avg_percentage=round(avg_percentage, 2),
        subjects_count=subjects_count,
        recent_results=recent_results,
    )


# ADD STUDENT (ADMIN ONLY) 
@app.route("/students/add", methods=["GET", "POST"])
@login_required
@admin_required
def add_student():
    if request.method == "POST":
        roll_no = request.form["roll_no"]
        name = request.form["name"]
        class_name = request.form["class_name"]
        dob = request.form["dob"]  # YYYY-MM-DD

        conn = get_db()
        cur = conn.cursor()

        try:
            cur.execute(
                "INSERT INTO students (roll_no, name, class_name, dob) VALUES (?, ?, ?, ?)",
                (roll_no, name, class_name, dob),
            )
            conn.commit()
            flash("Student added!", "success")
        except sqlite3.IntegrityError:
            flash("Roll number already exists!", "error")

        conn.close()
        return redirect(url_for("add_student"))

    return render_template("add_student.html")


# ADD RESULT (STAFF) 
@app.route("/results/add", methods=["GET", "POST"])
@login_required
@staff_required
def add_result():
    if request.method == "POST":
        roll_no = request.form["roll_no"]
        subject = request.form["subject"]
        marks = request.form["marks"]
        max_marks = request.form["max_marks"]

        try:
            marks = int(marks)
            max_marks = int(max_marks)
            if max_marks <= 0 or marks < 0 or marks > max_marks:
                raise ValueError
        except ValueError:
            flash("Please enter valid numeric marks (0 ≤ marks ≤ max_marks).", "error")
            return redirect(url_for("add_result"))

        conn = get_db()
        cur = conn.cursor()

        cur.execute("SELECT * FROM students WHERE roll_no=?", (roll_no,))
        student = cur.fetchone()

        if not student:
            conn.close()
            flash("Student not found!", "error")
            return redirect(url_for("add_result"))

        cur.execute(
            "INSERT INTO results (student_id, subject, marks, max_marks) VALUES (?, ?, ?, ?)",
            (student["id"], subject, marks, max_marks),
        )
        conn.commit()
        conn.close()

        flash("Result added!", "success")
        return redirect(url_for("add_result"))

    return render_template("add_result.html")


# SEARCH RESULT (STAFF) 
@app.route("/results/search", methods=["GET", "POST"])
@login_required
@staff_required
def search_result():
    if request.method == "POST":
        roll_no = request.form["roll_no"]

        conn = get_db()
        cur = conn.cursor()

        cur.execute("SELECT * FROM students WHERE roll_no=?", (roll_no,))
        student = cur.fetchone()

        if not student:
            conn.close()
            flash("Student not found!", "error")
            return redirect(url_for("search_result"))

        cur.execute("SELECT * FROM results WHERE student_id=?", (student["id"],))
        results = cur.fetchall()
        conn.close()

        total_obtained = sum(r["marks"] for r in results) if results else 0
        total_max = sum(r["max_marks"] for r in results) if results else 0
        percentage = (total_obtained / total_max * 100) if total_max > 0 else 0

        return render_template(
            "show_result.html",
            student=student,
            results=results,
            total_obtained=total_obtained,
            total_max=total_max,
            percentage=round(percentage, 2),
        )

    return render_template("search_result.html")


# STUDENT DASHBOARD 
@app.route("/student/dashboard")
@login_required
def student_dashboard():
    if session.get("role") != "student":
        flash("Only students can access this page!", "error")
        return redirect(url_for("index"))

    student_id = session.get("student_id")

    conn = get_db()
    cur = conn.cursor()

    cur.execute("SELECT * FROM students WHERE id=?", (student_id,))
    student = cur.fetchone()

    cur.execute("SELECT * FROM results WHERE student_id=?", (student_id,))
    results = cur.fetchall()
    conn.close()

    total_obtained = sum(r["marks"] for r in results) if results else 0
    total_max = sum(r["max_marks"] for r in results) if results else 0
    percentage = (total_obtained / total_max * 100) if total_max > 0 else 0

    return render_template(
        "student_result.html",
        student=student,
        results=results,
        total_obtained=total_obtained,
        total_max=total_max,
        percentage=round(percentage, 2),
    )


# EDIT RESULT (STAFF) 
@app.route("/results/edit/<int:id>", methods=["GET", "POST"])
@login_required
@staff_required
def edit_result(id):
    conn = get_db()
    cur = conn.cursor()

    cur.execute("SELECT * FROM results WHERE id=?", (id,))
    result = cur.fetchone()

    if not result:
        conn.close()
        flash("Result not found!", "error")
        return redirect(url_for("index"))

    if request.method == "POST":
        subject = request.form["subject"]
        marks = request.form["marks"]
        max_marks = request.form["max_marks"]

        try:
            marks = int(marks)
            max_marks = int(max_marks)
            if max_marks <= 0 or marks < 0 or marks > max_marks:
                raise ValueError
        except ValueError:
            flash("Please enter valid numeric marks (0 ≤ marks ≤ max_marks).", "error")
            conn.close()
            return redirect(url_for("edit_result", id=id))

        cur.execute(
            "UPDATE results SET subject=?, marks=?, max_marks=? WHERE id=?",
            (subject, marks, max_marks, id),
        )
        conn.commit()
        conn.close()

        flash("Result updated!", "success")
        return redirect(url_for("index"))

    conn.close()
    return render_template("edit_result.html", result=result)


# DELETE RESULT (STAFF)
@app.route("/results/delete/<int:id>")
@login_required
@staff_required
def delete_result(id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM results WHERE id=?", (id,))
    conn.commit()
    conn.close()

    flash("Result deleted!", "success")
    return redirect(url_for("index"))


# EXPORT RESULT TO PDF 
@app.route("/results/pdf/<roll_no>")
@login_required
def export_result_pdf(roll_no):
    # Students can only download their own result
    if session.get("role") == "student":
        if roll_no != session.get("student_roll_no"):
            flash("You can only download your own result!", "error")
            return redirect(url_for("student_dashboard"))

    conn = get_db()
    cur = conn.cursor()

    cur.execute("SELECT * FROM students WHERE roll_no=?", (roll_no,))
    student = cur.fetchone()

    if not student:
        conn.close()
        flash("Student not found!", "error")
        return redirect(url_for("index"))

    cur.execute("SELECT * FROM results WHERE student_id=?", (student["id"],))
    results = cur.fetchall()
    conn.close()

    total_obtained = sum(r["marks"] for r in results) if results else 0
    total_max = sum(r["max_marks"] for r in results) if results else 0
    percentage = (total_obtained / total_max * 100) if total_max > 0 else 0

    # Generate PDF in memory
    buffer = BytesIO()
    p = canvas.Canvas(buffer, pagesize=letter)
    width, height = letter

    y = height - 50
    p.setFont("Helvetica-Bold", 16)
    p.drawString(50, y, "Student Result Report")
    y -= 40

    p.setFont("Helvetica", 12)
    p.drawString(50, y, f"Name: {student['name']}")
    y -= 20
    p.drawString(50, y, f"Roll No: {student['roll_no']}")
    y -= 20
    p.drawString(50, y, f"Class: {student['class_name']}")
    y -= 20
    p.drawString(50, y, f"DOB: {student['dob']}")
    y -= 30

    p.setFont("Helvetica-Bold", 12)
    p.drawString(50, y, "Subject")
    p.drawString(250, y, "Marks")
    p.drawString(350, y, "Max Marks")
    y -= 15
    p.line(50, y, 450, y)
    y -= 20

    p.setFont("Helvetica", 12)
    for r in results:
        if y < 100:
            p.showPage()
            y = height - 50
            p.setFont("Helvetica", 12)
        p.drawString(50, y, r["subject"])
        p.drawString(250, y, str(r["marks"]))
        p.drawString(350, y, str(r["max_marks"]))
        y -= 20

    y -= 20
    p.setFont("Helvetica-Bold", 12)
    p.drawString(50, y, f"Total: {total_obtained} / {total_max}")
    y -= 20
    p.drawString(50, y, f"Percentage: {round(percentage, 2)}%")

    p.showPage()
    p.save()
    buffer.seek(0)

    filename = f"{student['roll_no']}_result.pdf"
    return send_file(
        buffer,
        as_attachment=True,
        download_name=filename,
        mimetype="application/pdf",
    )


# MAIN 
if __name__ == "__main__":
    if not os.path.exists(DATABASE):
        open(DATABASE, "w").close()

    init_db()
    app.run(debug=True)
