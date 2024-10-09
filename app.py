import json
import logging
from flask import Flask, request, render_template, send_file, redirect, url_for, session, flash
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
import requests
import csv
import io

# Setup Flask
app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///entities.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = 'your_secret_key'  # Set a secret key for session management
db = SQLAlchemy(app)

# Setup logging untuk debugging
logging.basicConfig(level=logging.DEBUG)

# Model database untuk akun pengguna
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)

# Model database untuk entitas hasil pencarian
class Entity(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    entry_number = db.Column(db.Integer, nullable=False)
    key = db.Column(db.String(100), nullable=False)
    value = db.Column(db.Text, nullable=False)
    info_leak = db.Column(db.Text, nullable=True)

# Tabel sementara untuk entitas yang dipilih
class SelectedEntity(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    entity_id = db.Column(db.Integer, db.ForeignKey('entity.id'), nullable=False, unique=True)

# Model untuk menyimpan hasil pencarian sementara
class SearchResult(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    query = db.Column(db.String(200), nullable=False)
    result_json = db.Column(db.Text, nullable=False)

# Buat ulang tabel jika perlu
with app.app_context():
    db.create_all()  # Membuat tabel jika belum ada

# Dictionary untuk emoji
emoji_dict = {
    "Email": "🛧",
    "Phone": "📞",
    "FullName": "👤",
    "NickName": "🆔",
    "Gender": "⚧",
    "Address": "🏠",
    "City": "🏢️",
    "Location": "📍",
    "Date": "📅",
    "Price": "💵",
    "Company": "🏦"
}

@app.route('/')
def home():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    return render_template('index.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        user = User.query.filter_by(username=username).first()
        if user and check_password_hash(user.password, password):
            session['user_id'] = user.id
            flash('Login berhasil', 'success')
            return redirect(url_for('results'))  # Redirect ke halaman search query
        else:
            flash('Username atau password salah', 'danger')

    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        hashed_password = generate_password_hash(password, method='sha256')

        user = User.query.filter_by(username=username).first()
        if user:
            flash('Username sudah terdaftar', 'danger')
        else:
            new_user = User(username=username, password=hashed_password)
            db.session.add(new_user)
            db.session.commit()
            flash('Registrasi berhasil, silakan login', 'success')
            return redirect(url_for('login'))

    return render_template('register.html')

@app.route('/logout')
def logout():
    session.pop('user_id', None)
    flash('Logout berhasil', 'success')
    return redirect(url_for('login'))

@app.route('/results', methods=['GET'])
def results():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    user_input = request.args.get('query')
    page = int(request.args.get('page', 1))

    if not user_input:
        return render_template('index.html', error="Masukkan query pencarian.")

    logging.debug(f"User input: {user_input}")

    # Reset pilihan checkbox saat pencarian baru
    if page == 1:
        db.session.query(SelectedEntity).delete()
        db.session.commit()

    # Cek apakah pencarian ini sudah ada di database
    existing_search = db.session.query(SearchResult).filter_by(query=user_input).first()

    if existing_search:
        # Ambil hasil pencarian dari database jika ada
        json_response = json.loads(existing_search.result_json)
        num_of_results = json_response.get('NumOfResults', 0)
        entities_data = json_response.get('List', {})
        logging.debug(f"Hasil pencarian ditemukan di database: {num_of_results} entitas")
    else:
        # Kirim permintaan ke API
        data = {
            "token": "REDACTED:REDACTED",
            "request": user_input,
            "lang": "id"
        }

        response = requests.post('https://server.leakosint.com/', json=data)

        if response.status_code == 200:
            json_response = response.json()
            logging.debug(f"Response dari API: {json.dumps(json_response, indent=2)}")

            num_of_results = json_response.get('NumOfResults', 0)
            entities_data = json_response.get('List', {})

            logging.debug(f"API memberikan {num_of_results} hasil")

            # Simpan hasil pencarian di database
            search_result = SearchResult(query=user_input, result_json=json.dumps(json_response))
            db.session.add(search_result)
            db.session.commit()
        else:
            logging.error(f"Gagal mengambil data dari API, status code: {response.status_code}")
            return f"Gagal mengambil data dari API, status code: {response.status_code}"

    # Simpan entitas dari API ke dalam database jika pencarian baru
    if not existing_search:
        db.session.query(Entity).delete()  # Hapus entitas lama dari database
        db.session.commit()

        if not entities_data:
            logging.error("Tidak ada data entitas di List hasil API!")
            return render_template('index.html', error="Tidak ada entitas ditemukan di hasil API.")

        for i, (entity_name, entity_info) in enumerate(entities_data.items(), start=1):
            logging.debug(f"Processing entity: {entity_name} with data {entity_info}")
            data_entries = entity_info.get('Data', [])
            info_leak = entity_info.get('InfoLeak', '')

            for entry in data_entries:
                entry_json = json.dumps(entry)
                entity = Entity(name=entity_name, entry_number=i, key='Data', value=entry_json, info_leak=info_leak)
                db.session.add(entity)
                logging.debug(f"Entitas {entity_name} disimpan ke database.")

        db.session.commit()

    # Ambil entitas dari database untuk halaman saat ini
    per_page = 5
    entities = Entity.query.paginate(page=page, per_page=per_page, error_out=False)

    if not entities.items:
        logging.warning(f"Tidak ada entitas yang ditemukan di database untuk halaman {page}")

    # Ambil semua entitas yang sudah dipilih dari tabel SelectedEntity
    selected_entity_ids = [se.entity_id for se in SelectedEntity.query.all()]

    # Parsing JSON string menjadi objek Python sebelum dikirim ke template
    parsed_entities = []
    for entity in entities.items:
        parsed_value = json.loads(entity.value)
        entity_with_emoji = []

        for key, value in parsed_value.items():
            emoji = emoji_dict.get(key, '👤')
            entity_with_emoji.append(f"{emoji} {key}: {value}")

        parsed_entities.append({
            "id": entity.id,
            "name": entity.name,
            "entry_number": entity.entry_number,
            "data": entity_with_emoji,
            "info_leak": entity.info_leak
        })

    return render_template(
        'result.html',
        entities=parsed_entities,
        total_results=num_of_results,
        page=page,
        total_pages=entities.pages,
        selected_entity_ids=selected_entity_ids  # Mengirim ID entitas yang sudah dipilih
    )

@app.route('/save-selection', methods=['POST'])
def save_selection():
    entity_id = int(request.form.get('entity_id'))
    is_checked = request.form.get('is_checked') == 'true'

    if is_checked:
        if not SelectedEntity.query.filter_by(entity_id=entity_id).first():
            selected_entity = SelectedEntity(entity_id=entity_id)
            db.session.add(selected_entity)
            db.session.commit()
            logging.debug(f"Entity dengan ID {entity_id} disimpan ke tabel sementara.")
    else:
        selected_entity = SelectedEntity.query.filter_by(entity_id=entity_id).first()
        if selected_entity:
            db.session.delete(selected_entity)
            db.session.commit()
            logging.debug(f"Entity dengan ID {entity_id} dihapus dari tabel sementara.")

    return "Selection updated", 200

# Hanya ekspor entitas yang dicentang dari hasil pencarian
@app.route('/export', methods=['POST'])
def export():
    # Ambil data dari tabel SelectedEntity untuk mengetahui entitas yang dipilih
    selected_entities = SelectedEntity.query.all()

    if not selected_entities:
        logging.debug("Tidak ada entri yang dipilih untuk diekspor.")
        return "Tidak ada entri yang dipilih untuk diekspor."

    selected_entries = [se.entity_id for se in selected_entities]
    logging.debug(f"Exporting {len(selected_entries)} selected entities.")

    output = io.StringIO()
    writer = csv.writer(output)

    # Set header dinamis untuk CSV tanpa emoji
    all_columns = set()
    data_to_write = []

    # Ambil data entitas yang dipilih dari database
    for entry_id in selected_entries:
        entity = Entity.query.get(entry_id)
        if entity:
            value_dict = json.loads(entity.value)  # Parse JSON value dari database
            info_leak = entity.info_leak

            # Tambahkan semua kunci ke dalam set untuk membuat header CSV dinamis
            all_columns.update(value_dict.keys())

            # Simpan data entitas untuk penulisan ke CSV nanti
            row_data = {**value_dict, "Entity Type": entity.name, "InfoLeak": info_leak}
            data_to_write.append(row_data)

    # Buat header CSV tanpa emoji
    csv_columns = ["Entity Type"] + sorted(all_columns) + ["InfoLeak"]
    writer.writerow(csv_columns)

    # Tulis data entitas ke dalam CSV
    for row in data_to_write:
        row_to_write = [row.get(col, "") for col in csv_columns]  # Isi nilai yang hilang dengan kosong
        writer.writerow(row_to_write)

    output.seek(0)

    # Kirim file CSV untuk diunduh (gunakan encoding UTF-8)
    return send_file(io.BytesIO(output.getvalue().encode('utf-8')), mimetype='text/csv', as_attachment=True, download_name='result.csv')

if __name__ == '__main__':
    app.run(debug=True)