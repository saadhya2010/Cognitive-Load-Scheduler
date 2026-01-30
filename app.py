from flask import Flask, request, render_template, redirect
import os
import csv
from datetime import datetime, date
from google import genai
from google.genai import types
import json

client = genai.Client(api_key="api_key_here") 

BASE_DIR = "users"

system_instructions = """
    You are a kind and helpful cognitive load scheduler assistant.

    Instructions:
    1. You will always see the user's latest input, past chat history, and today's scheduled tasks.
    2. Only make a task suggestion if you have enough information from the user about their personality, habits, workload, and preferences. Prompt for more information if needed before suggesting a task or schedule update.
    3. When suggesting tasks, consider the user's existing schedule to avoid conflicts and ensure a balanced workload.
    4. Prioritize tasks that help the user manage cognitive load effectively, breaking down complex tasks into smaller, manageable parts when necessary.
    5. If the user input requires a task suggestion or schedule update, respond ONLY in JSON format as a list of task objects. 
        Each task object must have these fields: 
        - date (YYYY-MM-DD)
        - start_time (HH:MM, 24-hour)
        - end_time (HH:MM, 24-hour)
        - task (string)
        - source (User or AI)
    6. If the user input is general chat or not a task request, respond normally as text (string).
    7. Do not mix JSON and text; JSON is only for task suggestions.
    8. Always aim to help the user manage cognitive load effectively.
    9. Refer to these research articles for cognitive load theory, management and scheduling strategies, and feel free to use other online sources to get good information to base suggestions off of:
    - https://doi.org/10.1016/S0959-4752(01)00021-4
    - https://doi.org/10.1016/j.chb.2008.12.007
    - https://doi.org/10.1016/j.ijpsycho.2017.10.004
    - https://doi.org/10.1027/1016-9040/a000138
    - https://doi.org/10.1016/j.ijproman.2006.02.010
    - https://doi.org/10.1016/j.intell.2013.04.008
    10. Always format times in 24-hour format in your JSON responses.

    Example JSON response for tasks:
    [
        {"date": "2026-01-29", "start_time": "14:00", "end_time": "15:00", "task": "Math homework", "source": "AI"},
        {"date": "2026-01-29", "start_time": "16:00", "end_time": "16:30", "task": "Read article", "source": "AI"}
    ]
"""

def ensure_user_folder(username):
    user_dir = os.path.join(BASE_DIR, username)
    os.makedirs(user_dir, exist_ok=True)

    chat_path = os.path.join(user_dir, "chat.csv")
    if not os.path.exists(chat_path):
        with open(chat_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["sender", "message", "timestamp"])

    tasks_path = os.path.join(user_dir, "tasks.csv")
    if not os.path.exists(tasks_path):
        with open(tasks_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["date", "start_time", "end_time", "task", "source"])

def append_chat(username, sender, message):
    chat_path = os.path.join(BASE_DIR, username, "chat.csv")
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    with open(chat_path, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([sender, message, timestamp])

def load_chat(username):
    chat_path = os.path.join(BASE_DIR, username, "chat.csv")
    chat = []

    with open(chat_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            chat.append((row["sender"], row["message"]))

    return chat

def load_tasks(username, selected_date=None):
    tasks = []
    user_folder = os.path.join(BASE_DIR, username)
    csv_path = os.path.join(user_folder, "tasks.csv")

    if not os.path.exists(csv_path):
        return tasks

    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if selected_date is None or row["date"] == selected_date:
                tasks.append(row)

    tasks.sort(key=lambda t: t["start_time"])
    return tasks

def append_task(username, date, start_time, end_time, task, source):
    tasks_path = os.path.join(BASE_DIR, username, "tasks.csv")
    with open(tasks_path, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([date, start_time, end_time, task, source])

def to_24h(t_str):
    try:
        return datetime.strptime(t_str.strip(), "%I:%M %p").strftime("%H:%M")
    except ValueError:
        return t_str

app = Flask(__name__)

@app.route("/")
def landing():
    return render_template("landing.html")

@app.route("/entry", methods=["POST"])
def entry():
    name = request.form.get("name", "").strip().lower()
    if not name:
        return redirect("/")
    return redirect(f"/{name}")

@app.route("/<username>", methods=["GET", "POST"])
def user_page(username):
    ensure_user_folder(username)

    chat = load_chat(username)
    today = date.today().isoformat()
    tasks = load_tasks(username, today)
    latest_tasks_from_ai = None

    if request.method == "POST":
        if "accept_task_btn" in request.form:
            tasks_json = request.form.get("accept_task_btn")
            accepted_tasks = json.loads(tasks_json)
            for t in accepted_tasks:
                append_task(username, t["date"], t["start_time"], t["end_time"], t["task"], t["source"])
            return redirect(f"/{username}")

        if "task_name" in request.form:
            task_name = request.form.get("task_name", "").strip()
            start_time = request.form.get("start_time", "").strip()
            end_time = request.form.get("end_time", "").strip()
            if task_name and start_time and end_time:
                append_task(username, today, start_time, end_time, task_name, "User")
            return redirect(f"/{username}")

        user_input = request.form.get("chat_input", "").strip()

        if user_input:            
            append_chat(username, "User", user_input)

            context = {
                "user_input": user_input,
                "chat_history": [{"sender": sender, "message": message} for sender, message in chat],
                "scheduled_tasks": tasks
            }
            context_str = json.dumps(context, indent=2)

            response = client.models.generate_content(
                model="gemini-3-flash-preview", 
                config=types.GenerateContentConfig(
                    system_instruction=system_instructions
                ),
                contents=context_str
            )
            ai_response = response.text
            append_chat(username, "AI", ai_response)

            latest_tasks_from_ai = None
            try:
                parsed = json.loads(ai_response)
                if isinstance(parsed, list):
                    latest_tasks_from_ai = parsed
            except json.JSONDecodeError:
                latest_tasks_from_ai = None

    chat = load_chat(username)
    return render_template("user_page.html", username=username, chat=chat, tasks=tasks, latest=latest_tasks_from_ai)

if __name__ == "__main__":
    app.run(debug=True)
