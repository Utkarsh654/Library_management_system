from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
import sqlite3
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime

app = Flask(__name__)
app.secret_key = "library-management-secret-key-change-this"

DB = "library.db"

def get_db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def init_db():
    conn = get_db()
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        email TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL,
        role TEXT NOT NULL DEFAULT 'user'
    );

    CREATE TABLE IF NOT EXISTS books (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        author TEXT NOT NULL,
        category TEXT,
        quantity INTEGER NOT NULL DEFAULT 1
    );

    CREATE TABLE IF NOT EXISTS issued_books (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        book_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        issue_date TEXT NOT NULL,
        return_date TEXT,
        status TEXT NOT NULL DEFAULT 'Issued',
        FOREIGN KEY(book_id) REFERENCES books(id) ON DELETE RESTRICT,
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE RESTRICT
    );
    """)
    admin = conn.execute("SELECT id FROM users WHERE email=?", ("admin@gmail.com",)).fetchone()
    if not admin:
        conn.execute(
            "INSERT INTO users(name,email,password,role) VALUES(?,?,?,?)",
            ("Administrator", "admin@gmail.com", generate_password_hash("admin123"), "admin")
        )
    conn.commit()
    conn.close()

def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return wrapper

def admin_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if session.get("role") != "admin":
            flash("Admin access required.", "danger")
            return redirect(url_for("dashboard"))
        return f(*args, **kwargs)
    return wrapper

@app.route("/")
def home():
    if "user_id" in session:
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form["name"].strip()
        email = request.form["email"].strip().lower()
        password = request.form["password"]

        if not name or not email or not password:
            flash("All fields are required.", "danger")
            return redirect(url_for("register"))

        conn = get_db()
        try:
            conn.execute(
                "INSERT INTO users(name,email,password,role) VALUES(?,?,?,?)",
                (name, email, generate_password_hash(password), "user")
            )
            conn.commit()
            flash("Registration successful. Please login.", "success")
            return redirect(url_for("login"))
        except sqlite3.IntegrityError:
            flash("Email already registered.", "danger")
            return redirect(url_for("register"))
        finally:
            conn.close()
    return render_template("register.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form["email"].strip().lower()
        password = request.form["password"]

        conn = get_db()
        user = conn.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
        conn.close()

        if user and check_password_hash(user["password"], password):
            session["user_id"] = user["id"]
            session["name"] = user["name"]
            session["role"] = user["role"]
            return redirect(url_for("dashboard"))

        flash("Invalid email or password.", "danger")
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out.", "success")
    return redirect(url_for("login"))

@app.route("/dashboard")
@login_required
def dashboard():
    conn = get_db()
    total_books = conn.execute("SELECT COALESCE(SUM(quantity),0) FROM books").fetchone()[0]
    total_titles = conn.execute("SELECT COUNT(*) FROM books").fetchone()[0]
    total_users = conn.execute("SELECT COUNT(*) FROM users WHERE role='user'").fetchone()[0]
    issued = conn.execute("SELECT COUNT(*) FROM issued_books WHERE status='Issued'").fetchone()[0]
    my_issued = conn.execute(
        "SELECT COUNT(*) FROM issued_books WHERE user_id=? AND status='Issued'",
        (session["user_id"],)
    ).fetchone()[0]
    conn.close()
    return render_template(
        "dashboard.html",
        total_books=total_books,
        total_titles=total_titles,
        total_users=total_users,
        issued=issued,
        my_issued=my_issued
    )

@app.route("/books")
@login_required
def books():
    q = request.args.get("q", "").strip()
    conn = get_db()
    if q:
        rows = conn.execute(
            "SELECT * FROM books WHERE title LIKE ? OR author LIKE ? OR category LIKE ? ORDER BY id DESC",
            (f"%{q}%", f"%{q}%", f"%{q}%")
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM books ORDER BY id DESC").fetchall()
    conn.close()
    return render_template("books.html", books=rows, q=q)

@app.route("/books/add", methods=["POST"])
@admin_required
def add_book():
    title = request.form["title"].strip()
    author = request.form["author"].strip()
    category = request.form["category"].strip()
    quantity = request.form.get("quantity", "1")

    try:
        quantity = int(quantity)
        if quantity < 1:
            raise ValueError
    except ValueError:
        flash("Quantity must be a positive number.", "danger")
        return redirect(url_for("books"))

    if not title or not author:
        flash("Title and author are required.", "danger")
        return redirect(url_for("books"))

    conn = get_db()
    conn.execute(
        "INSERT INTO books(title,author,category,quantity) VALUES(?,?,?,?)",
        (title, author, category, quantity)
    )
    conn.commit()
    conn.close()
    flash("Book added successfully.", "success")
    return redirect(url_for("books"))

@app.route("/books/delete/<int:book_id>", methods=["POST"])
@admin_required
def delete_book(book_id):
    conn = get_db()
    active = conn.execute(
        "SELECT id FROM issued_books WHERE book_id=? AND status='Issued'",
        (book_id,)
    ).fetchone()
    if active:
        flash("This book is currently issued and cannot be deleted.", "danger")
    else:
        conn.execute("DELETE FROM books WHERE id=?", (book_id,))
        conn.commit()
        flash("Book deleted.", "success")
    conn.close()
    return redirect(url_for("books"))

@app.route("/issue", methods=["GET", "POST"])
@login_required
def issue_book():
    if request.method == "POST":
        book_id = request.form.get("book_id")
        conn = get_db()
        book = conn.execute("SELECT * FROM books WHERE id=?", (book_id,)).fetchone()
        if not book or book["quantity"] <= 0:
            conn.close()
            flash("Book is not available.", "danger")
            return redirect(url_for("issue_book"))

        already = conn.execute(
            "SELECT id FROM issued_books WHERE book_id=? AND user_id=? AND status='Issued'",
            (book_id, session["user_id"])
        ).fetchone()
        if already:
            conn.close()
            flash("You already have this book issued.", "danger")
            return redirect(url_for("issue_book"))

        conn.execute("UPDATE books SET quantity=quantity-1 WHERE id=?", (book_id,))
        conn.execute(
            "INSERT INTO issued_books(book_id,user_id,issue_date,status) VALUES(?,?,?,?)",
            (book_id, session["user_id"], datetime.now().strftime("%Y-%m-%d"), "Issued")
        )
        conn.commit()
        conn.close()
        flash("Book issued successfully.", "success")
        return redirect(url_for("my_books"))

    conn = get_db()
    available = conn.execute("SELECT * FROM books WHERE quantity>0 ORDER BY title").fetchall()
    conn.close()
    return render_template("issue.html", books=available)

@app.route("/my-books")
@login_required
def my_books():
    conn = get_db()
    rows = conn.execute("""
        SELECT issued_books.*, books.title, books.author
        FROM issued_books
        JOIN books ON books.id=issued_books.book_id
        WHERE issued_books.user_id=?
        ORDER BY issued_books.id DESC
    """, (session["user_id"],)).fetchall()
    conn.close()
    return render_template("my_books.html", rows=rows)

@app.route("/return/<int:issue_id>", methods=["POST"])
@login_required
def return_book(issue_id):
    conn = get_db()
    issue = conn.execute(
        "SELECT * FROM issued_books WHERE id=? AND user_id=? AND status='Issued'",
        (issue_id, session["user_id"])
    ).fetchone()
    if not issue:
        conn.close()
        flash("Invalid return request.", "danger")
        return redirect(url_for("my_books"))

    conn.execute(
        "UPDATE issued_books SET status='Returned', return_date=? WHERE id=?",
        (datetime.now().strftime("%Y-%m-%d"), issue_id)
    )
    conn.execute("UPDATE books SET quantity=quantity+1 WHERE id=?", (issue["book_id"],))
    conn.commit()
    conn.close()
    flash("Book returned successfully.", "success")
    return redirect(url_for("my_books"))

@app.route("/users")
@admin_required
def users():
    conn = get_db()
    rows = conn.execute("SELECT id,name,email,role FROM users ORDER BY id DESC").fetchall()
    conn.close()
    return render_template("users.html", users=rows)

@app.route("/admin/issues")
@admin_required
def all_issues():
    conn = get_db()
    rows = conn.execute("""
        SELECT issued_books.*, books.title, users.name, users.email
        FROM issued_books
        JOIN books ON books.id=issued_books.book_id
        JOIN users ON users.id=issued_books.user_id
        ORDER BY issued_books.id DESC
    """).fetchall()
    conn.close()
    return render_template("issues.html", rows=rows)

@app.route("/admin/return/<int:issue_id>", methods=["POST"])
@admin_required
def admin_return(issue_id):
    conn = get_db()
    issue = conn.execute(
        "SELECT * FROM issued_books WHERE id=? AND status='Issued'", (issue_id,)
    ).fetchone()
    if issue:
        conn.execute(
            "UPDATE issued_books SET status='Returned', return_date=? WHERE id=?",
            (datetime.now().strftime("%Y-%m-%d"), issue_id)
        )
        conn.execute("UPDATE books SET quantity=quantity+1 WHERE id=?", (issue["book_id"],))
        conn.commit()
        flash("Book returned successfully.", "success")
    else:
        flash("Issue record not found.", "danger")
    conn.close()
    return redirect(url_for("all_issues"))

if __name__ == "__main__":
    init_db()
    app.run(debug=True)
