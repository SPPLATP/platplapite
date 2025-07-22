from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify
import sqlite3
from werkzeug.security import generate_password_hash, check_password_hash 
from functools import wraps
import os
from datetime import datetime
from werkzeug.utils import secure_filename
from flask_mail import Mail, Message


def semana_atual():
    # Suponha que semana seja string tipo "2025-W23"
    now = datetime.now()
    return now.strftime("%Y-W%U")  # Exemplo, ajuste conforme sua lógica

app = Flask(__name__)
app.secret_key = 'chave-secreta-muito-segura'
DATABASE = 'palpites.db'
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = 'suportpalpites@gmail.com'
app.config['MAIL_PASSWORD'] = 'nktqbtkxzactvxmq'  # Pode usar um "App Password" se estiver usando Gmail
app.config['MAIL_DEFAULT_SENDER'] = 'suportpalpites@gmail.com'

mail = Mail(app)
# Pasta para uploads
app.config['UPLOAD_FOLDER'] = 'static/uploads/'
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)


#Pasta para comprovantes.
UPLOAD_CFOLDER = 'static/comprovantes'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'pdf'}

app.config['UPLOAD_CFOLDER'] = UPLOAD_CFOLDER

# Cria as pastas se não existirem
if not os.path.exists(UPLOAD_CFOLDER):
    os.makedirs(UPLOAD_CFOLDER)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def get_db_connection():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    # Se quiser apagar o banco para recriar do zero, descomente as linhas abaixo:
    # if os.path.exists(DATABASE):
    #     os.remove(DATABASE)
    #     print("Banco antigo apagado para recriação.")

    conn = get_db_connection()
    c = conn.cursor()

    #Tabela User
    c.execute('''
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        first_name TEXT NOT NULL,
        last_name TEXT NOT NULL,
        email TEXT NOT NULL UNIQUE,
        phone TEXT NOT NULL,
        password TEXT NOT NULL,
        status TEXT DEFAULT 'pendente',
        photo TEXT NOT NULL,
        created_at  DEFAULT CURRENT_TIMESTAMP
    )
    ''')

    #Tabela Admins
    c.execute('''
    CREATE TABLE IF NOT EXISTS admins (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT NOT NULL UNIQUE,
        password TEXT NOT NULL
    )
    ''')
    
    #Tabela Palpites
    c.execute('''
    CREATE TABLE IF NOT EXISTS palpites (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    dia INTEGER NOT NULL,
    semana TEXT NOT NULL,
    horario TEXT NOT NULL,
    oldata varchar(50)          
    )
    ''')
    
    # Criar tabela de pagamentos
    c.execute('''
    CREATE TABLE IF NOT EXISTS pagamentos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT NOT NULL,
        forma_comprovacao TEXT NOT NULL,
        comprovante_path TEXT,
        referencia TEXT,
        codigo_levantamento TEXT,
        data_envio TEXT DEFAULT CURRENT_TIMESTAMP,
        status TEXT DEFAULT 'pendente',
        tipo_pagamento TEXT DEFAULT 'ativacao'

    )
    ''')

    # Cria admin padrão
    senha_admin = generate_password_hash('Dp@2025!')
    c.execute("INSERT OR IGNORE INTO admins (username, password) VALUES (?, ?)", ('whoami', senha_admin))

    conn.commit()
    conn.close()
    print("Banco criado, admin padrão inserido e tabelas criadas")


# Decorators para login de usuário e admin

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_email' not in session:
            flash('Você precisa estar logado para acessar essa página.', 'warning')
            return redirect(url_for('login'))

        conn = get_db_connection()
        c = conn.cursor()
        c.execute("SELECT status FROM users WHERE email=?", (session['user_email'],))
        user = c.fetchone()
        conn.close()

        if not user or user['status'] != 'aprovado':
            flash('Sua conta ainda não foi aprovada.', 'danger')
            return redirect(url_for('ativar'))

        return f(*args, **kwargs)
    return decorated_function


def admin_login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('admin_logged_in'):
            flash('Você precisa estar logado como admin para acessar essa página.', 'warning')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def usuario_ativo(user_id):
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    
    # Verifica se já tem algum pagamento aprovado (ativação inicial)
    c.execute('''
        SELECT COUNT(*) FROM pagamentos 
        WHERE user_id = ? AND status = 'aprovado'
    ''', (user_id,))
    total_aprovados = c.fetchone()[0]
    if total_aprovados == 0:
        conn.close()
        return False  # Usuário não ativado ainda
    
    # Verifica pagamento na última semana
    c.execute('''
        SELECT COUNT(*) FROM pagamentos
        WHERE user_id = ? AND status = 'aprovado'
        AND date(data_envio) >= date('now', '-7 days')
    ''', (user_id,))
    pagamentos_ultima_semana = c.fetchone()[0]
    conn.close()
    
    return pagamentos_ultima_semana > 0

def salvar_pagamento(user_id, forma_comprovacao, comprovante_path=None, referencia=None, codigo_levantamento=None, tipo='ativacao'):
    import sqlite3

    DATABASE = 'palpites.db'  # Certifique-se de definir corretamente
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()

    # Criar a tabela caso não exista
    c.execute('''
        CREATE TABLE IF NOT EXISTS pagamentos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            forma_comprovacao TEXT,
            comprovante_path TEXT,
            referencia TEXT,
            codigo_levantamento TEXT,
            tipo TEXT,
            status TEXT DEFAULT 'pendente',
            data_envio TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # Inserir pagamento corretamente, incluindo `status`
    c.execute('''
        INSERT INTO pagamentos (user_id, forma_comprovacao, comprovante_path, referencia, codigo_levantamento, tipo, status)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (user_id, forma_comprovacao, comprovante_path, referencia, codigo_levantamento, tipo, 'pendente'))

    conn.commit()
    conn.close()

def enviar_email(destinatario, assunto, mensagem):
    try:
        msg = Message(assunto, recipients=[destinatario])
        msg.body = mensagem
        mail.send(msg)
        print(f"E-mail enviado para {destinatario}: {assunto}")
    except Exception as e:
        print(f"Erro ao enviar e-mail: {e}")
        
# Rotas
@app.route('/')
def home():
    return render_template('home.html')




@app.route('/cadastro_form', methods=['GET', 'POST'])
def cadastro_form():
    if request.method == 'POST':
        first_name = request.form['first_name']
        last_name = request.form['last_name']
        email = request.form['email']
        phone = request.form['phone']
        password = request.form['password']
        confirma_senha = request.form['confirma_senha']
        photo = request.files.get('photo')

        if not photo or photo.filename == '':
            flash('A foto de perfil é obrigatória.', 'danger')
            return redirect(url_for('cadastro_form'))

        if not password or password != confirma_senha:
            flash('As senhas não coincidem.', 'erro')
            return redirect(url_for('cadastro_form'))

        conn = get_db_connection()
        c = conn.cursor()
        c.execute("SELECT * FROM users WHERE email=?", (email,))
        if c.fetchone():
            flash('Email já cadastrado.', 'danger')
            conn.close()
            return redirect(url_for('cadastro_form'))

        # Criar diretório e salvar imagem
        os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
        photo_filename = os.path.join(app.config['UPLOAD_FOLDER'], photo.filename)
        photo.save(photo_filename)

        hashed_password = generate_password_hash(password)

        # ✅ Insere no banco diretamente
        try:
            c.execute("""
                INSERT INTO users (first_name, last_name, email, phone, photo, password, status)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (first_name, last_name, email, phone, photo_filename, hashed_password, 'pendente'))

            user_id = c.lastrowid  # 🔥 Obtém ID do usuário recém-cadastrado
            conn.commit()
            conn.close()

            # ✅ Armazena `user_id` na sessão para vincular ao pagamento
            session['user_id'] = user_id

            flash('Cadastro realizado com sucesso! Agora, efetue o pagamento para ativar sua conta.', 'success')
            return redirect(url_for('ativar'))  # 🔥 Redireciona automaticamente para ativação

        except sqlite3.Error as e:
            flash(f"Erro ao salvar no banco: {e}", 'danger')
            print(f"Erro no SQLite: {e}")
            return redirect(url_for('cadastro_form'))

    return render_template('cadastro_form.html')



@app.route('/admin')
@admin_login_required
def admin():
    conn = get_db_connection()
    c = conn.cursor()

    # Busca usuários pendentes de ativação
    c.execute("SELECT * FROM users WHERE status = 'pendente' ORDER BY created_at DESC")
    users_pendentes = c.fetchall()

    # Busca pagamentos pendentes
    c.execute("""
        SELECT p.id, p.user_id, u.first_name || ' ' || u.last_name AS user_name,
               p.data_envio, p.forma_comprovacao, p.comprovante_path,
               p.referencia, p.codigo_levantamento, p.status, p.tipo_pagamento
        FROM pagamentos p
        JOIN users u ON p.user_id = u.id
        WHERE p.status = 'pendente'
        ORDER BY p.data_envio DESC
    """)
    pagamentos_pendentes = c.fetchall()

    # Classifica pagamentos para exibir corretamente
    pagamentos_ativacao = []
    pagamentos_palpites = []

    for pagamento in pagamentos_pendentes:
        if pagamento["tipo_pagamento"] == "ativacao":
            pagamentos_ativacao.append(pagamento)
        elif pagamento["tipo_pagamento"] == "palpite":
            pagamentos_palpites.append(pagamento)

    conn.close()

    return render_template(
        'auth/admin.html',
        users=users_pendentes if pagamentos_ativacao else [],
        pagamentos=pagamentos_ativacao if pagamentos_ativacao else pagamentos_palpites
    )






@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        identifier = request.form['identifier']
        password = request.form['password']

        conn = get_db_connection()
        c = conn.cursor()

        # Verifica se é um usuário comum
        c.execute("SELECT * FROM users WHERE email=?", (identifier,))
        user = c.fetchone()

        # Verifica se é um admin
        c.execute("SELECT * FROM admins WHERE username=?", (identifier,))
        admin = c.fetchone()

        # Login de administrador
        if admin and check_password_hash(admin['password'], password):
            session.clear()
            session['admin_logged_in'] = True
            session['admin_email'] = admin['username']
            session['admin_id'] = admin['id']
            conn.close()
            flash('Login de administrador realizado com sucesso!', 'success')
            return redirect(url_for('admin'))

        # Login de usuário comum
        if user and check_password_hash(user['password'], password):
            session.clear()
            session['user_logged_in'] = True
            session['user_email'] = user['email']
            session['user_id'] = user['id']

            # Verifica se o usuário está aprovado
            if user['status'] != 'aprovado':
                conn.close()
                flash("Você precisa ativar sua conta antes de acessar os palpites.", "warning")
                return redirect(url_for("ativar", tipo='ativacao'))

            # Verifica se há um pagamento de ativação aprovado
            c.execute("""
                SELECT id FROM pagamentos 
                WHERE user_id = ? AND tipo_pagamento = 'ativacao' AND status = 'aprovado'
                ORDER BY data_envio DESC LIMIT 1
            """, (user['id'],))
            ativacao_aprovada = c.fetchone()

            # Se o usuário tem ativação aprovada, ele pode acessar palpites
            if ativacao_aprovada:
                conn.close()
                flash("Login realizado com sucesso!", "success")
                return redirect(url_for("palpites_usuario"))

            # Verifica se há um pagamento pendente do tipo 'palpite'
            c.execute("""
                SELECT id FROM pagamentos 
                WHERE user_id = ? AND tipo_pagamento = 'palpite' AND status = 'pendente'
                ORDER BY data_envio DESC LIMIT 1
            """, (user['id'],))
            palpite_pendente = c.fetchone()

            # Se há um pagamento pendente de palpite, manda para /pagar
            if palpite_pendente:
                conn.close()
                flash("Há um pagamento de palpite pendente! Redirecionando para pagamento.", "warning")
                return redirect(url_for("pagar", tipo='palpite'))

            conn.close()
            flash("Login realizado com sucesso!", "success")
            return redirect(url_for('palpites_usuario'))

        conn.close()
        flash('Usuário ou senha incorretos.', 'danger')
        return redirect(url_for('login'))

    return render_template('login.html')





@app.route('/palpites_usuario')
@login_required
def palpites_usuario():
    user_id = session.get('user_id')
    if not user_id:
        flash("Sessão expirada. Faça login novamente.", "warning")
        return redirect(url_for('login'))

    conn = get_db_connection()
    cursor = conn.cursor()

    # 🚀 Verifica se o usuário possui pelo menos um pagamento de ativação aprovado
    cursor.execute("""
        SELECT id FROM pagamentos
        WHERE user_id = ? AND tipo_pagamento = 'ativacao' AND status = 'aprovado'
        ORDER BY data_envio DESC LIMIT 1
    """, (user_id,))
    ativacao_ok = cursor.fetchone()
    if not ativacao_ok:
        conn.close()
        flash("Você precisa ativar sua conta antes de ver palpites.", "warning")
        return redirect(url_for("pagar", tipo='palpite'))

    # 🚀 Busca o último palpite disponível
    cursor.execute('SELECT dia, semana, horario FROM palpites ORDER BY id DESC LIMIT 1')
    resultado = cursor.fetchone()
    conn.close()

    if resultado:
        dia, semana, horarios_str = resultado
        horarios_lista = [h.strip() for h in horarios_str.split(',')]
        palpites = [{
            'dia': dia,
            'semana': semana,
            'horarios': horarios_lista
        }]
    else:
        palpites = []

    return render_template('palpites_usuario.html', palpites=palpites)






@app.route('/logout')
def logout():
    session.clear()
    flash('Você saiu da conta.', 'success')
    return redirect(url_for('home'))


@app.route('/ativar', methods=['GET', 'POST'])
#@login_required
def ativar():
    user_id = session.get('user_id')
    if not user_id:
        flash('Você precisa estar logado para ativar.', 'danger')
        return redirect(url_for('login'))

    conn = get_db_connection()
    c = conn.cursor()

    # Configuração do caminho correto para armazenar comprovantes
    UPLOAD_FOLDER = 'static/comprovantes/'
    app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

    if request.method == 'POST':
        forma = request.form.get('formaComprovacao')

        if forma == 'comprovante':
            arquivo = request.files.get('comprovante')
            if not arquivo or arquivo.filename == '':
                flash('Por favor, envie o comprovante.', 'danger')
                return redirect(request.url)

            if allowed_file(arquivo.filename):
                filename = secure_filename(f"{user_id}_ativacao_{arquivo.filename}")
                file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                arquivo.save(file_path)  # Salva corretamente na pasta 'static/comprovantes/'

                c.execute("""
                    INSERT INTO pagamentos (user_id, forma_comprovacao, comprovante_path, status, tipo_pagamento, data_envio)
                    VALUES (?, ?, ?, ?, ?, datetime('now'))
                """, (user_id, 'comprovante', filename, 'pendente', 'ativacao'))

                print(f"Comprovante salvo em: {file_path}")  # Debug para verificar o caminho do arquivo

        elif forma == 'codigo':
            referencia = request.form.get('referencia', '').strip()
            codigo = request.form.get('codigo_levantamento', '').strip()

            if not referencia or not codigo:
                flash('Preencha os dois campos.', 'danger')
                return redirect(request.url)

            c.execute("""
                INSERT INTO pagamentos (user_id, forma_comprovacao, referencia, codigo_levantamento, status, tipo_pagamento, data_envio)
                VALUES (?,?, ?, ?, ?, ?, datetime('now'))
            """, (user_id, 'codigo', referencia, codigo, 'pendente', 'ativacao'))

        conn.commit()
        conn.close()

        flash('Pagamento enviado! Aguarde a aprovação.', 'success')
        return redirect(url_for('aguardando_aprovacao'))

    return render_template('ativar.html')




@app.route('/auth/admin/aprovar_user/<int:user_id>', methods=['POST'])
@admin_login_required
def aprovar_user(user_id):
    conn = get_db_connection()
    c = conn.cursor()

    print(f"Tentando aprovar usuário {user_id}")

    # Busca status anterior
    c.execute("SELECT status, email, first_name FROM users WHERE id=?", (user_id,))
    user = c.fetchone()
    status_antes = user[0] if user else None
    user_email = user[1] if user else None
    user_name = user[2] if user else None
    print(f"Status antes: {status_antes}")

    # Atualiza status para aprovado
    c.execute("UPDATE users SET status='aprovado' WHERE id=?", (user_id,))
    conn.commit()

    # Confirma status após a atualização
    c.execute("SELECT status FROM users WHERE id=?", (user_id,))
    status_depois = c.fetchone()
    print(f"Status depois: {status_depois}")

    # Enviar e-mail de ativação da conta, se o usuário foi aprovado
    if user_email and user_name:
        base_url = request.host_url  # Captura automaticamente a URL base do servidor
        login_url = f"{base_url}login"

        assunto = "Sua conta foi ativada!"
        mensagem = f"""Olá {user_name},\n\nSua conta na Plataforma Palpite foi ativada com sucesso! Agora você já pode acessar seu primeiro palpite.\n\n🔗 **Faça login aqui:** {login_url}\n\nAtenciosamente,\nEquipe Palpite"""
        
        enviar_email(user_email, assunto, mensagem)

        print(f"E-mail enviado para {user_email} com link de login: {login_url}")

    conn.close()

    flash('Usuário aprovado com sucesso!', 'success')
    return redirect(url_for('admin'))




@app.route('/auth/admin/aprovar_pagamento/<int:pagamento_id>', methods=['POST'])
@admin_login_required
def aprovar_pagamento(pagamento_id):
    conn = get_db_connection()
    c = conn.cursor()

    # Busca informações do pagamento
    c.execute("SELECT user_id, tipo_pagamento FROM pagamentos WHERE id=?", (pagamento_id,))
    pagamento = c.fetchone()

    if not pagamento:
        flash('Pagamento não encontrado.', 'danger')
        conn.close()
        return redirect(url_for('admin'))

    user_id = pagamento['user_id']

    # Atualiza o status do pagamento para 'aprovado'
    c.execute("UPDATE pagamentos SET status='aprovado' WHERE id=?", (pagamento_id,))

    # Verifica se já existe um pagamento aprovado do tipo 'ativacao' para este usuário
    c.execute("""
        SELECT id FROM pagamentos 
        WHERE user_id = ? AND tipo_pagamento = 'ativacao' AND status = 'aprovado'
        LIMIT 1
    """, (user_id,))
    ativacao_existente = c.fetchone()

    # Se ainda não houver um pagamento de ativação aprovado, transforma este pagamento em ativação
    if not ativacao_existente:
        c.execute("UPDATE pagamentos SET tipo_pagamento='ativacao' WHERE id=?", (pagamento_id,))

    conn.commit()
    conn.close()

    flash(f'Pagamento de {pagamento["tipo_pagamento"]} aprovado com sucesso!', 'success')
    return redirect(url_for('admin'))

@app.route('/auth/admin/rejeitar_pagamento/<int:pagamento_id>', methods=['POST'])
@admin_login_required
def rejeitar_pagamento(pagamento_id):
    conn = get_db_connection()
    c = conn.cursor()

    # Verifica se o pagamento existe
    c.execute("SELECT id FROM pagamentos WHERE id=?", (pagamento_id,))
    pagamento = c.fetchone()

    if not pagamento:
        flash('Pagamento não encontrado.', 'danger')
        conn.close()
        return redirect(url_for('admin'))

    # Atualiza o status do pagamento para 'rejeitado'
    c.execute("UPDATE pagamentos SET status='rejeitado' WHERE id=?", (pagamento_id,))

    conn.commit()
    conn.close()

    flash('Pagamento rejeitado com sucesso!', 'danger')
    return redirect(url_for('admin'))



@app.route('/auth/admin/rejeitar_user/<int:user_id>', methods=['POST'])
@admin_login_required
def rejeitar_user(user_id):
    conn = get_db_connection()
    c = conn.cursor()

    # 🚨 Remove o usuário da base de dados
    c.execute("DELETE FROM users WHERE id=?", (user_id,))
    conn.commit()
    conn.close()

    flash('Usuário rejeitado e removido!', 'danger')
    return redirect(url_for('admin'))














@app.route('/aguardando_aprovacao')
def aguardando_aprovacao():
    user_id = session.get('user_id')
    if not user_id:
        flash('Você precisa estar logado.', 'danger')
        return redirect(url_for('login'))

    conn = get_db_connection()
    c = conn.cursor()
    
    c.execute("SELECT email, first_name FROM users WHERE id=?", (user_id,))
    user = c.fetchone()
    
    conn.close()

    if user:
        return render_template('aguardando_aprovacao.html', user=user)
    else:
        flash("Erro ao recuperar informações do usuário.", "danger")
        return redirect(url_for('login'))



@app.route('/pagar', methods=['GET', 'POST'])
@login_required
def pagar():
    user_id = session.get('user_id')
    if not user_id:
        flash('Você precisa estar logado para pagar.', 'danger')
        return redirect(url_for('login'))

    conn = get_db_connection()
    c = conn.cursor()

    # Define a pasta correta para os comprovantes
    UPLOAD_FOLDER = 'static/comprovantes/'
    app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

    # Recebe o tipo do pagamento que usuário quer pagar (default 'palpite')
    tipo_pagamento = request.args.get('tipo', 'palpite')

    # Busca status do pagamento mais recente desse tipo para o usuário
    c.execute("""
        SELECT status FROM pagamentos 
        WHERE user_id=? AND tipo_pagamento=? 
        ORDER BY data_envio DESC LIMIT 1
    """, (user_id, tipo_pagamento))
    pagamento_status_result = c.fetchone()
    pagamento_status = pagamento_status_result[0] if pagamento_status_result else 'pendente'

    if request.method == 'POST':
        forma = request.form.get('formaComprovacao')
        file = request.files.get('comprovante')

        if forma == 'comprovante':
            if not file or file.filename == '':
                flash('Por favor, envie um comprovante.', 'danger')
                return redirect(url_for('pagar', tipo=tipo_pagamento))

            if allowed_file(file.filename):
                filename = secure_filename(f"{user_id}_{tipo_pagamento}_{file.filename}")
                file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                file.save(file_path)  # Agora salva corretamente em 'static/comprovantes/'

                # Insere pagamento com status pendente para aprovação manual
                c.execute("""
                    INSERT INTO pagamentos (user_id, forma_comprovacao, comprovante_path, status, tipo_pagamento, data_envio) 
                    VALUES (?, ?, ?, 'pendente', ?, datetime('now'))
                """, (user_id, 'comprovante', filename, tipo_pagamento))

                print(f"Comprovante salvo em: {file_path}")  # Debug para confirmar o caminho correto

        elif forma == 'codigo':
            referencia = request.form.get('referencia', '').strip()
            codigo = request.form.get('codigo_levantamento', '').strip()

            if not referencia or not codigo:
                flash('Preencha os dois campos.', 'danger')
                return redirect(url_for('pagar', tipo=tipo_pagamento))

            c.execute("""
                INSERT INTO pagamentos (user_id, forma_comprovacao, referencia, codigo_levantamento, status, tipo_pagamento, data_envio) 
                VALUES (?, 'codigo', ?, ?, 'pendente', ?, datetime('now'))
            """, (user_id, referencia, codigo, tipo_pagamento))

        conn.commit()
        conn.close()

        flash('Pagamento enviado! Aguarde aprovação.', 'success')
        return redirect(url_for('aguardando_aprovacao'))  # 🔥 Redireciona corretamente!

    conn.close()
    return render_template('pagar.html', pagamento_status=pagamento_status, tipo_pagamento=tipo_pagamento)





@app.route('/auth/admin_palpites', methods=['GET', 'POST'])
@admin_login_required
def admin_palpites():
    conn = get_db_connection()
    c = conn.cursor()

    if request.method == 'POST':
        dia = int(request.form['dia'])
        semana = request.form['semana']
        horarios_raw = request.form['horarios']
        horarios = ', '.join([h.strip() for h in horarios_raw.split(',') if h.strip()])
        oldata = datetime.now().strftime('%Y%m%d')

        # Verifica se já existe um palpite para o mesmo dia e semana
        existing = c.execute(
            'SELECT id FROM palpites WHERE dia = ? AND semana = ?',
            (dia, semana)
        ).fetchone()

        if existing:
            # Atualiza o palpite existente e a data oldata
            c.execute(
                'UPDATE palpites SET horario = ?, oldata = ? WHERE dia = ? AND semana = ?',
                (horarios, oldata, dia, semana)
            )
        else:
            # Insere novo palpite com oldata
            c.execute(
                'INSERT INTO palpites (dia, semana, horario, oldata) VALUES (?, ?, ?, ?)',
                (dia, semana, horarios, oldata)
            )

        conn.commit()

        # Atualiza tipo_pagamento para 'palpite' apenas quando status for 'aprovado'
        c.execute("""
            UPDATE pagamentos 
            SET tipo_pagamento = 'palpite' 
            WHERE status = 'aprovado' AND tipo_pagamento != 'palpite'
        """)

        conn.commit()

        # 🔥 Buscar emails e nomes de usuários que atendem aos critérios
        usuarios = c.execute("""
            SELECT u.email, u.first_name 
            FROM users u
            JOIN pagamentos p ON u.id = p.user_id  
            WHERE u.status = 'aprovado'  
            AND p.status = 'aprovado'  
            AND (p.tipo_pagamento = 'ativacao' OR p.tipo_pagamento = 'palpite')
        """).fetchall()

        # 🔥 Enviar email para todos os usuários aprovados com nome personalizado e link correto
        pagar_url = "http://appsppt.duckdns.org:8888/pagar?origem=email"  # 🔥 Link fixo com parâmetro de origem

        for email, nome in usuarios:
            try:
                mensagem = f"Olá {nome}! Você tem um novo palpite disponível. Acesse o link abaixo, efetue seu pagamento semanal e garanta seu acesso!\n\n{pagar_url}"
                enviar_email(email, 'NOVO PALPITE', mensagem)
                print(f"Email enviado com sucesso para {nome} ({email})!")
            except Exception as e:
                print(f"Erro ao enviar email para {nome} ({email}): {e}")

        conn.close()

        flash('Palpite atualizado e emails enviados para usuários aprovados!', 'success')
        return redirect(url_for('admin_palpites', dia=dia, semana=semana))

    # GET: Busca palpites existentes
    dia = request.args.get('dia', type=int)
    semana = request.args.get('semana', type=str)

    if dia is not None and semana:
        palpites = c.execute(
            'SELECT * FROM palpites WHERE dia = ? AND semana = ?',
            (dia, semana)
        ).fetchall()
    else:
        rec = c.execute('SELECT dia, semana FROM palpites ORDER BY id DESC LIMIT 1').fetchone()
        if rec:
            dia, semana = rec['dia'], rec['semana']
            palpites = c.execute(
                'SELECT * FROM palpites WHERE dia = ? AND semana = ?',
                (dia, semana)
            ).fetchall()
        else:
            palpites = []

    conn.close()

    return render_template('auth/admin_palpites.html', palpites=palpites, dia=dia, semana=semana)









@app.route('/admin_usuarios')
@admin_login_required
def admin_usuarios():
    total_aprovados = 0 
    conn = get_db_connection()
    c = conn.cursor()

    c.execute("SELECT id, first_name, last_name, email, phone, photo, created_at FROM users WHERE status = 'aprovado' ORDER BY created_at DESC")
    usuarios = c.fetchall()
    #ver total de usuarios aprovados
    c.execute("SELECT COUNT(*) FROM users WHERE status = 'aprovado'")
    total_aprovados = c.fetchone()[0]

    conn.close()

    return render_template('auth/admin_usuarios.html', usuarios=usuarios,total_aprovados=total_aprovados)

@app.route('/excluir_usuario/<int:user_id>', methods=['POST'])
@admin_login_required
def excluir_usuario(user_id):
    conn = get_db_connection()
    c = conn.cursor()

    # Remove usuário do banco de dados
    c.execute("DELETE FROM users WHERE id = ?", (user_id,))
    conn.commit()
    conn.close()

    flash('Usuário excluído com sucesso!', 'success')
    return redirect(url_for('admin_usuarios'))



@app.route('/contacto')
@login_required
def contacto():
    return render_template('contacto.html')



if __name__ == '__main__':
    init_db()
    app.run()#8888
