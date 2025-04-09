from flask import Flask, render_template, request, redirect, url_for
import sqlite3
import os
import random
import string
from collections import defaultdict

app = Flask(__name__)
app.secret_key = 'your-secret-key'


def generate_slug(name):
    base = name.lower().replace(' ', '-')
    suffix = ''.join(random.choices(string.ascii_lowercase + string.digits, k=6))
    return f"{base}-{suffix}"


# Create tables if needed
with sqlite3.connect("database.db") as conn:
    c = conn.cursor()

    c.execute('''
        CREATE TABLE IF NOT EXISTS groups (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL
        )
    ''')

    # Add missing columns
    c.execute("PRAGMA table_info(groups)")
    group_columns = [col[1] for col in c.fetchall()]
    if "members" not in group_columns:
        c.execute("ALTER TABLE groups ADD COLUMN members TEXT")
    if "slug" not in group_columns:
        c.execute("ALTER TABLE groups ADD COLUMN slug TEXT")

    c.execute('''
        CREATE TABLE IF NOT EXISTS expenses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            group_id INTEGER,
            payer TEXT,
            amount REAL,
            description TEXT,
            split_between TEXT,
            FOREIGN KEY (group_id) REFERENCES groups(id)
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            group_id INTEGER,
            payer TEXT,
            payee TEXT,
            amount REAL,
            FOREIGN KEY (group_id) REFERENCES groups(id)
        )
    ''')

    conn.commit()


def calculate_balances(expenses, payments):
    paid = defaultdict(float)
    owed = defaultdict(float)

    for expense in expenses:
        _, payer, amount, _, split_between = expense
        people = [name.strip() for name in split_between.split(',') if name.strip()]
        split_amount = amount / len(people)
        paid[payer] += amount
        for person in people:
            owed[person] += split_amount

    for payment in payments:
        _, payer, payee, amount = payment
        owed[payer] -= amount
        paid[payee] -= amount

    balances = {}
    people = set(paid.keys()) | set(owed.keys())
    for person in people:
        balances[person] = round(paid.get(person, 0) - owed.get(person, 0), 2)

    return balances


def smart_settle_up(balances):
    creditors = []
    debtors = []

    for person, balance in balances.items():
        if balance > 0:
            creditors.append([person, balance])
        elif balance < 0:
            debtors.append([person, -balance])

    settlements = []
    i, j = 0, 0

    while i < len(debtors) and j < len(creditors):
        debtor, debt = debtors[i]
        creditor, credit = creditors[j]
        amount = min(debt, credit)

        settlements.append(f"{debtor} should pay {creditor} ${amount:.2f}")

        debtors[i][1] -= amount
        creditors[j][1] -= amount

        if debtors[i][1] == 0:
            i += 1
        if creditors[j][1] == 0:
            j += 1

    return settlements


@app.route('/')
def index():
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute("SELECT slug, name FROM groups")
    groups = c.fetchall()
    conn.close()
    return render_template('index.html', groups=groups)


@app.route('/add_group', methods=['POST'])
def add_group():
    name = request.form['group_name']
    members = request.form['members']
    slug = generate_slug(name)

    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute("INSERT INTO groups (name, members, slug) VALUES (?, ?, ?)", (name, members, slug))
    conn.commit()
    conn.close()
    return redirect(url_for('group_detail', slug=slug))


@app.route('/group/<slug>')
def group_detail(slug):
    conn = sqlite3.connect('database.db')
    c = conn.cursor()

    c.execute("SELECT id, name, members FROM groups WHERE slug=?", (slug,))
    group_data = c.fetchone()
    if not group_data:
        return "Group not found", 404

    group_id, group_name, members_raw = group_data
    members = [m.strip() for m in members_raw.split(',') if m.strip()]

    c.execute("SELECT id, payer, amount, description, split_between FROM expenses WHERE group_id=?", (group_id,))
    expenses = c.fetchall()

    c.execute("SELECT id, payer, payee, amount FROM payments WHERE group_id=?", (group_id,))
    payments = c.fetchall()

    conn.close()

    balances = calculate_balances(expenses, payments)
    suggestions = smart_settle_up(balances)

    return render_template('group.html',
                           group_id=group_id,
                           group_name=group_name,
                           slug=slug,
                           members=members,
                           expenses=expenses,
                           payments=payments,
                           balances=balances,
                           suggestions=suggestions)


@app.route('/add_expense/<int:group_id>', methods=['POST'])
def add_expense(group_id):
    payer = request.form['payer']
    amount = float(request.form['amount'])
    description = request.form['description']
    split_between = ', '.join(request.form.getlist('split_between'))

    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute("INSERT INTO expenses (group_id, payer, amount, description, split_between) VALUES (?, ?, ?, ?, ?)",
              (group_id, payer, amount, description, split_between))
    c.execute("SELECT slug FROM groups WHERE id=?", (group_id,))
    slug = c.fetchone()[0]
    conn.commit()
    conn.close()

    return redirect(url_for('group_detail', slug=slug))


@app.route('/record_payment/<int:group_id>', methods=['POST'])
def record_payment(group_id):
    payer = request.form['payer']
    payee = request.form['payee']
    amount = float(request.form['amount'])

    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute("INSERT INTO payments (group_id, payer, payee, amount) VALUES (?, ?, ?, ?)",
              (group_id, payer, payee, amount))
    c.execute("SELECT slug FROM groups WHERE id=?", (group_id,))
    slug = c.fetchone()[0]
    conn.commit()
    conn.close()

    return redirect(url_for('group_detail', slug=slug))


@app.route('/edit_expense/<int:expense_id>', methods=['POST'])
def edit_expense(expense_id):
    group_id = int(request.form['group_id'])
    payer = request.form['payer']
    amount = float(request.form['amount'])
    description = request.form['description']
    split_between = ', '.join(request.form.getlist('split_between'))

    conn = sqlite3.connect("database.db")
    c = conn.cursor()
    c.execute("UPDATE expenses SET payer=?, amount=?, description=?, split_between=? WHERE id=?",
              (payer, amount, description, split_between, expense_id))
    c.execute("SELECT slug FROM groups WHERE id=?", (group_id,))
    slug = c.fetchone()[0]
    conn.commit()
    conn.close()
    return redirect(url_for('group_detail', slug=slug))


@app.route('/delete_expense/<int:expense_id>', methods=['POST'])
def delete_expense(expense_id):
    group_id = int(request.form['group_id'])

    conn = sqlite3.connect("database.db")
    c = conn.cursor()
    c.execute("DELETE FROM expenses WHERE id=?", (expense_id,))
    c.execute("SELECT slug FROM groups WHERE id=?", (group_id,))
    slug = c.fetchone()[0]
    conn.commit()
    conn.close()
    return redirect(url_for('group_detail', slug=slug))


@app.route('/edit_payment/<int:payment_id>', methods=['POST'])
def edit_payment(payment_id):
    group_id = int(request.form['group_id'])
    payer = request.form['payer']
    payee = request.form['payee']
    amount = float(request.form['amount'])

    conn = sqlite3.connect("database.db")
    c = conn.cursor()
    c.execute("UPDATE payments SET payer=?, payee=?, amount=? WHERE id=?",
              (payer, payee, amount, payment_id))
    c.execute("SELECT slug FROM groups WHERE id=?", (group_id,))
    slug = c.fetchone()[0]
    conn.commit()
    conn.close()
    return redirect(url_for('group_detail', slug=slug))


@app.route('/delete_payment/<int:payment_id>', methods=['POST'])
def delete_payment(payment_id):
    group_id = int(request.form['group_id'])

    conn = sqlite3.connect("database.db")
    c = conn.cursor()
    c.execute("DELETE FROM payments WHERE id=?", (payment_id,))
    c.execute("SELECT slug FROM groups WHERE id=?", (group_id,))
    slug = c.fetchone()[0]
    conn.commit()
    conn.close()
    return redirect(url_for('group_detail', slug=slug))


app.run(host='0.0.0.0', port=81)