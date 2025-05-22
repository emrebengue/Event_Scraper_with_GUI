from flask import (
    Flask,
    render_template,
    request,
    jsonify,
    send_file,
    redirect,
    url_for,
    flash,
    session,
)
import json
import os
from algorithm_based_extraction import main
import tempfile
import time
import pandas as pd
import io
from database import db, User, Event
from functools import wraps
from io import BytesIO
from extract_pdf import upload_file_to_s3, extract_text_from_pdf

app = Flask(__name__)
app.config["SECRET_KEY"] = os.urandom(24)
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///app.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db.init_app(app)

# Create database tables
with app.app_context():
    db.create_all()

# Directory to store generated JSON files
OUTPUT_DIR = "output"
os.makedirs(OUTPUT_DIR, exist_ok=True)


def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login"))
        return f(*args, **kwargs)

    return decorated_function


@app.route("/")
def index():
    if "user_id" in session:
        return redirect(url_for("main_page"))
    return render_template("index.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        user = User.query.filter_by(username=username).first()

        if user and user.check_password(password):
            session["user_id"] = user.id
            session["username"] = user.username
            return redirect(url_for("main_page"))
        flash("Invalid username or password")
    return render_template("login.html")


@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        username = request.form.get("username")
        email = request.form.get("email")
        password = request.form.get("password")

        if User.query.filter_by(username=username).first():
            flash("Username already exists")
            return redirect(url_for("signup"))

        if User.query.filter_by(email=email).first():
            flash("Email already exists")
            return redirect(url_for("signup"))

        user = User(username=username, email=email)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()

        flash("Account created successfully")
        return redirect(url_for("login"))
    return render_template("signup.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))


@app.route("/main")
@login_required
def main_page():
    # Get user's saved events
    events = (
        Event.query.filter_by(user_id=session["user_id"])
        .order_by(Event.created_at.desc())
        .all()
    )
    return render_template(
        "main.html", current_user={"username": session["username"]}, events=events
    )


@app.route("/process", methods=["POST"])
@login_required
def process_url():
    try:
        url = request.form.get("url")
        if not url:
            return jsonify({"error": "URL is required"}), 400

        # Process the URL using main11.py
        result = main(url)

        # If result is a string (JSON string), parse it into a dictionary
        if isinstance(result, str):
            try:
                result = json.loads(result)
            except json.JSONDecodeError as e:
                print(f"Error parsing JSON: {e}")
                result = {"data": result}

        # Generate a unique filename
        timestamp = int(time.time())
        filename = f"event_data_{timestamp}.json"
        filepath = os.path.join(OUTPUT_DIR, filename)

        # Save the JSON to a file
        with open(filepath, "w") as f:
            json.dump(result, f, indent=4)

        # Extract events from the result and save to database
        events_saved = save_events_to_db(result, url, session["user_id"])

        # Create HTML table from JSON data
        table_html = create_table_html(result)

        return jsonify(
            {
                "success": True,
                "table": table_html,
                "filename": filename,
                "data": result,
                "events_saved": events_saved,
            }
        )

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/upload-pdf", methods=["POST"])
@login_required
def upload_pdf():
    try:
        if "pdf" not in request.files:
            return jsonify({"error": "No PDF file provided"}), 400

        file = request.files["pdf"]
        if file.filename == "":
            return jsonify({"error": "Empty filename"}), 400

        # Save temporarily
        temp_path = os.path.join(tempfile.gettempdir(), file.filename)
        file.save(temp_path)

        # Upload to S3 and extract text
        s3_filename = upload_file_to_s3(temp_path, file.filename)
        extracted_text = extract_text_from_pdf(s3_filename)

        # Reuse your existing `main()` logic by calling it with the text
        result = main(extracted_text)

        if isinstance(result, str):
            try:
                result = json.loads(result)
            except json.JSONDecodeError as e:
                result = {"data": result}

        timestamp = int(time.time())
        filename = f"event_data_{timestamp}.json"
        filepath = os.path.join(OUTPUT_DIR, filename)

        with open(filepath, "w") as f:
            json.dump(result, f, indent=4)

        events_saved = save_events_to_db(result, "PDF Upload", session["user_id"])
        table_html = create_table_html(result)

        return jsonify(
            {
                "success": True,
                "table": table_html,
                "filename": filename,
                "data": result,
                "events_saved": events_saved,
            }
        )

    except Exception as e:
        return jsonify({"error": str(e)}), 500


def save_events_to_db(data, source_url, user_id):
    events_saved = 0

    try:
        # Case 1: plain list of events (e.g. from PDF LLM directly)
        if isinstance(data, list):
            for event_data in data:
                save_event(event_data, source_url, user_id)
                events_saved += 1
            return events_saved

        # Case 2: dict with top-level "events" key
        if "events" in data and isinstance(data["events"], list):
            for event_data in data["events"]:
                save_event(event_data, source_url, user_id)
                events_saved += 1
            return events_saved

        # Case 3: dict with nested events per URL
        for url, event_details in data.items():
            if isinstance(event_details, dict) and "events" in event_details:
                for event_data in event_details["events"]:
                    save_event(event_data, source_url, user_id)
                    events_saved += 1
            elif isinstance(event_details, list):
                for event_data in event_details:
                    save_event(event_data, source_url, user_id)
                    events_saved += 1

        return events_saved
    except Exception as e:
        print(f"Error saving events: {e}")
        return 0


def save_event(event_data, source_url, user_id):
    """Save a single event to the database"""
    if not isinstance(event_data, dict):
        return

    event = Event(
        name=event_data.get("name", "Unknown Event"),
        date=event_data.get("date", ""),
        time=event_data.get("time", ""),
        city=event_data.get("city", ""),
        state=event_data.get("state", ""),
        url=event_data.get("url", ""),
        source_url=source_url,
        user_id=user_id,
    )
    db.session.add(event)
    db.session.commit()


@app.route("/events")
@login_required
def view_events():
    """View all saved events"""
    events = (
        Event.query.filter_by(user_id=session["user_id"])
        .order_by(Event.created_at.desc())
        .all()
    )
    return render_template("events.html", events=events)


@app.route("/event/<int:event_id>")
@login_required
def view_event(event_id):
    """View details of a specific event"""
    event = Event.query.filter_by(
        id=event_id, user_id=session["user_id"]
    ).first_or_404()
    return render_template("event_details.html", event=event)


@app.route("/event/edit/<int:event_id>", methods=["GET", "POST"])
@login_required
def edit_event(event_id):
    """Edit a saved event"""
    event = Event.query.filter_by(
        id=event_id, user_id=session["user_id"]
    ).first_or_404()

    if request.method == "POST":
        event.name = request.form.get("name")
        event.date = request.form.get("date")
        event.time = request.form.get("time")
        event.city = request.form.get("city")
        event.state = request.form.get("state")
        event.url = request.form.get("url")

        try:
            db.session.commit()
            flash("Event updated successfully", "success")
            return redirect(url_for("view_events"))
        except Exception as e:
            db.session.rollback()
            flash(f"Error updating event: {str(e)}", "danger")

    return render_template("edit_event.html", event=event)


@app.route("/event/delete/<int:event_id>")
@login_required
def delete_event(event_id):
    """Delete a saved event"""
    event = Event.query.filter_by(
        id=event_id, user_id=session["user_id"]
    ).first_or_404()

    try:
        db.session.delete(event)
        db.session.commit()
        flash("Event deleted successfully", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Error deleting event: {str(e)}", "danger")

    return redirect(url_for("view_events"))


@app.route("/download/<filename>")
def download_file(filename):
    try:
        filepath = os.path.join(OUTPUT_DIR, filename)
        return send_file(filepath, as_attachment=True)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/download_excel/<filename>")
def download_excel(filename):
    try:
        filepath = os.path.join(OUTPUT_DIR, filename)
        with open(filepath, "r") as f:
            data = json.load(f)

        # Extract events data
        events = []
        if "events" in data and isinstance(data["events"], list):
            events = data["events"]
        else:
            # If the structure is different, try to extract events from nested structure
            for url, event_details in data.items():
                if isinstance(event_details, dict) and "events" in event_details:
                    events.extend(event_details["events"])
                elif isinstance(event_details, list):
                    events.extend(event_details)

        # Convert to pandas DataFrame
        if not events:
            return jsonify({"error": "No event data found"}), 404

        df = pd.DataFrame(events)

        # Create Excel file in memory
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine="openpyxl") as writer:
            df.to_excel(writer, index=False, sheet_name="Events")

            # Auto-adjust columns' width
            worksheet = writer.sheets["Events"]
            for i, col in enumerate(df.columns):
                max_length = max(df[col].astype(str).map(len).max(), len(col)) + 3
                worksheet.column_dimensions[chr(65 + i)].width = max_length

        output.seek(0)

        # Generate Excel filename from JSON filename
        excel_filename = filename.replace(".json", ".xlsx")

        return send_file(
            output,
            as_attachment=True,
            download_name=excel_filename,
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/view/<filename>")
def view_json(filename):
    try:
        filepath = os.path.join(OUTPUT_DIR, filename)
        with open(filepath, "r") as f:
            data = json.load(f)
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/export_events")
@login_required
def export_events():
    """Export all saved events to Excel"""
    events = Event.query.filter_by(user_id=session["user_id"]).all()

    if not events:
        flash("No events to export", "warning")
        return redirect(url_for("view_events"))

    # Convert to list of dictionaries for DataFrame
    event_data = []
    for event in events:
        event_data.append(
            {
                "Name": event.name,
                "Date": event.date,
                "Time": event.time,
                "City": event.city,
                "State": event.state,
                "URL": event.url,
                "Source URL": event.source_url,
                "Created": event.created_at.strftime("%Y-%m-%d %H:%M:%S"),
            }
        )

    # Create DataFrame and Excel file
    df = pd.DataFrame(event_data)
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Events")

        # Auto-adjust columns' width
        worksheet = writer.sheets["Events"]
        for i, col in enumerate(df.columns):
            max_length = max(df[col].astype(str).map(len).max(), len(col)) + 3
            worksheet.column_dimensions[chr(65 + i)].width = max_length

    output.seek(0)

    timestamp = int(time.time())
    return send_file(
        output,
        as_attachment=True,
        download_name=f"events_export_{timestamp}.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


def create_table_html(data):
    """Create an HTML table from the JSON data"""
    if not data or not isinstance(data, dict):
        return "<div class='alert alert-warning'>No event data found or invalid format.</div>"

    # Check if the data contains an 'events' key at the top level
    if "events" in data and isinstance(data["events"], list):
        # If we have a direct events array, process it
        return create_structured_event_html(data["events"])

    html = ""
    event_count = 0

    # For each URL in the data
    for url, event_details in data.items():
        # Extract a title from the URL
        url_parts = url.split("/")
        title = url_parts[-1].replace("-", " ").title()
        if title == "":
            title = url_parts[-2].replace("-", " ").title()

        html += f"<div class='card mb-4'>"
        html += f"<div class='card-header'>"
        html += f"<h5 class='mb-0'>{title} <a href='{url}' target='_blank'><i class='fas fa-external-link-alt ms-2'></i></a></h5>"
        html += f"</div>"
        html += f"<div class='card-body'>"

        # Check if event_details is a string or a nested structure
        if isinstance(event_details, str):
            # Format the event details with proper line breaks and highlight key information
            formatted_details = event_details

            # Highlight date, time, and location
            formatted_details = formatted_details.replace(
                "Date", "<strong>Date</strong>"
            )
            formatted_details = formatted_details.replace(
                "Time", "<strong>Time</strong>"
            )
            formatted_details = formatted_details.replace(
                "Location", "<strong>Location</strong>"
            )

            # Replace newlines with HTML breaks
            formatted_details = formatted_details.replace("\n", "<br>")

            html += f"<div class='event-details'>{formatted_details}</div>"
        else:
            # Check if this contains an 'events' key
            if (
                isinstance(event_details, dict)
                and "events" in event_details
                and isinstance(event_details["events"], list)
            ):
                html += create_structured_event_html(event_details["events"])
                event_count += len(event_details["events"])
            else:
                # Handle nested JSON structure
                html += create_structured_event_html(event_details)
                if isinstance(event_details, list):
                    event_count += len(event_details)

        html += f"</div>"
        html += f"</div>"

    # Add a summary of events found
    if event_count > 0:
        html = (
            f"<div class='alert alert-success mb-4'><i class='fas fa-check-circle me-2'></i> Found {event_count} events</div>"
            + html
        )

    return html


def create_structured_event_html(event_data):
    """Create structured HTML for nested event data"""
    if isinstance(event_data, list):
        # Handle list of events - this is the expected format for events array
        html = "<div class='row row-cols-1 row-cols-md-2 row-cols-lg-3 g-4'>"
        for event in event_data:
            html += f"<div class='col mb-4'>"
            html += f"<div class='card h-100'>"

            # Card header with event name
            event_name = event.get("name", "Event")
            html += f"<div class='card-header'>"
            html += f"<h5 class='mb-0'>{event_name}</h5>"
            html += f"</div>"

            # Card body with event details
            html += f"<div class='card-body'>"
            html += f"<ul class='list-group list-group-flush'>"

            # Date and Time
            date = event.get("date", "N/A")
            time = event.get("time", "N/A")
            html += f"<li class='list-group-item'><i class='fas fa-calendar-day me-2'></i> <strong>Date:</strong> {date}</li>"
            if time and time != "N/A":
                html += f"<li class='list-group-item'><i class='fas fa-clock me-2'></i> <strong>Time:</strong> {time}</li>"

            # Location
            city = event.get("city", "")
            state = event.get("state", "")
            location = ""
            if city and state:
                location = f"{city}, {state}"
            elif city:
                location = city
            elif state:
                location = state

            if location:
                html += f"<li class='list-group-item'><i class='fas fa-map-marker-alt me-2'></i> <strong>Location:</strong> {location}</li>"

            # URL if available
            url = event.get("url", "")
            if url:
                html += f"<li class='list-group-item'><i class='fas fa-link me-2'></i> <a href='{url}' target='_blank'>Event Details</a></li>"

            # Add any other fields that aren't standard
            for key, value in event.items():
                if (
                    key not in ["name", "date", "time", "city", "state", "url"]
                    and value
                ):
                    formatted_key = key.replace("_", " ").title()
                    html += f"<li class='list-group-item'><strong>{formatted_key}:</strong> {value}</li>"

            html += f"</ul>"
            html += f"</div>"  # End card-body
            html += f"</div>"  # End card
            html += f"</div>"  # End column

        html += "</div>"  # End row
        return html

    elif isinstance(event_data, dict):
        # Check if this is an events container
        if "events" in event_data and isinstance(event_data["events"], list):
            return create_structured_event_html(event_data["events"])

        # Handle dictionary of event properties
        html = "<table class='table table-striped table-bordered'>"

        # Sort keys to put important information first
        priority_keys = [
            "name",
            "title",
            "date",
            "time",
            "location",
            "city",
            "state",
            "venue",
            "address",
            "description",
        ]
        sorted_keys = sorted(
            event_data.keys(),
            key=lambda x: (
                0 if x.lower() in priority_keys else 1 if not x.startswith("_") else 2,
                priority_keys.index(x.lower()) if x.lower() in priority_keys else 999,
            ),
        )

        for key in sorted_keys:
            value = event_data[key]
            # Skip empty values
            if (
                value is None
                or value == ""
                or (isinstance(value, list) and len(value) == 0)
            ):
                continue

            # Format key for display
            formatted_key = key.replace("_", " ").title()
            if key.startswith("_"):
                formatted_key = formatted_key[1:]

            html += "<tr>"
            html += f"<th style='width: 30%'>{formatted_key}</th>"

            if isinstance(value, dict) or isinstance(value, list):
                # Nested structure
                html += f"<td>{create_structured_event_html(value)}</td>"
            else:
                # Simple value
                formatted_value = str(value)

                # Format URLs as links
                if formatted_value.startswith("http"):
                    formatted_value = f"<a href='{formatted_value}' target='_blank'>{formatted_value}</a>"

                # Format dates with special styling
                elif any(
                    date_word in key.lower() for date_word in ["date", "day", "time"]
                ):
                    formatted_value = (
                        f"<span class='text-primary fw-bold'>{formatted_value}</span>"
                    )

                # Format locations with special styling
                elif any(
                    loc_word in key.lower()
                    for loc_word in [
                        "location",
                        "venue",
                        "address",
                        "place",
                        "city",
                        "state",
                    ]
                ):
                    formatted_value = (
                        f"<span class='text-success'>{formatted_value}</span>"
                    )

                html += f"<td>{formatted_value}</td>"

            html += "</tr>"

        html += "</table>"
        return html

    else:
        # Handle primitive values
        return str(event_data)


if __name__ == "__main__":
    app.run(debug=True)
