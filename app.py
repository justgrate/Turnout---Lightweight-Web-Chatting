import os
from flask import Flask, render_template, request, redirect, url_for, flash
from flask_socketio import SocketIO, join_room, leave_room, emit
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from chat_manager import ChatManager
import emoji
from datetime import datetime
from functools import wraps

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('FLASK_SECRET_KEY', 'your-secret-key')
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///chat.db'
app.config['UPLOAD_FOLDER'] = 'static/uploads'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size
ALLOWED_EXTENSIONS = {'txt', 'pdf', 'png', 'jpg', 'jpeg', 'gif'}

db = SQLAlchemy(app)
socketio = SocketIO(app)
chat_manager = ChatManager()
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(120), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)
    messages = db.relationship('Message', backref='user', lazy=True, cascade="all, delete-orphan")
    reactions = db.relationship('MessageReaction', backref='user', lazy=True, cascade="all, delete-orphan")

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    content = db.Column(db.Text, nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    channel = db.Column(db.String(80), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    message_type = db.Column(db.String(10), default='text')

class MessageReaction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    message_id = db.Column(db.String(36), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    emoji = db.Column(db.String(8), nullable=False)

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            flash('You need to be an admin to access this page.')
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    return decorated_function

@login_manager.user_loader
def load_user(id):
    return User.query.get(int(id))

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def broadcast_user_list(channel):
    users = list(chat_manager.channels[channel])
    emit('user_list_update', {'users': users}, to=channel)

@app.route('/')
def index():
    if not current_user.is_authenticated:
        return redirect(url_for('login'))
    channels_with_counts = chat_manager.get_channels()
    return render_template('index.html', channels=channels_with_counts)

@app.route('/admin')
@login_required
@admin_required
def admin_dashboard():
    users = User.query.all()
    channels_with_counts = chat_manager.get_channels()
    messages = Message.query.order_by(Message.timestamp.desc()).limit(100).all()
    return render_template('admin_dashboard.html', 
                         users=users,
                         channels=channels_with_counts,
                         messages=messages)

@app.route('/admin/delete_user/<int:user_id>', methods=['POST'])
@login_required
@admin_required
def delete_user(user_id):
    user = User.query.get_or_404(user_id)
    
    # Prevent self-deletion
    if user == current_user:
        flash('You cannot delete your own account.')
        return redirect(url_for('admin_dashboard'))
    
    # Count number of admin users
    admin_count = User.query.filter_by(is_admin=True).count()
    
    # Prevent deletion of the last admin user
    if user.is_admin and admin_count <= 1:
        flash('Cannot delete the last admin user.')
        return redirect(url_for('admin_dashboard'))
    
    try:
        # Remove user from all channels
        for channel in chat_manager.channels.values():
            channel.discard(user.username)
        
        # Delete the user and their associated data
        db.session.delete(user)
        db.session.commit()
        flash(f'User {user.username} has been deleted successfully.')
    except Exception as e:
        db.session.rollback()
        flash('An error occurred while deleting the user.')
        app.logger.error(f'Error deleting user: {str(e)}')
    
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/toggle_admin/<int:user_id>', methods=['POST'])
@login_required
@admin_required
def toggle_admin(user_id):
    user = User.query.get_or_404(user_id)
    if user == current_user:
        flash('You cannot modify your own admin status')
    else:
        user.is_admin = not user.is_admin
        db.session.commit()
        flash(f'Admin status updated for {user.username}')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/delete_channel/<channel>', methods=['POST'])
@login_required
@admin_required
def delete_channel(channel):
    if channel in chat_manager.channels:
        # Notify users in the channel
        emit('status', {'msg': f'Channel {channel} has been deleted by admin'}, 
             to=channel, namespace='/')
        # Remove the channel
        chat_manager.channels.pop(channel)
        flash(f'Channel {channel} has been deleted')
    return redirect(url_for('admin_dashboard'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user = User.query.filter_by(username=username).first()
        
        if user and user.check_password(password):
            login_user(user)
            return redirect(url_for('index'))
        flash('Invalid username or password')
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        if User.query.filter_by(username=username).first():
            flash('Username already exists')
            return redirect(url_for('register'))
        
        user = User()
        user.username = username
        user.set_password(password)
        # Set the first user as admin
        if User.query.count() == 0:
            user.is_admin = True
        db.session.add(user)
        db.session.commit()
        
        login_user(user)
        return redirect(url_for('index'))
    return render_template('register.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route('/chat/<channel>')
@login_required
def chat(channel):
    return render_template('chat.html', channel=channel)

@app.route('/create_channel', methods=['POST'])
@login_required
def create_channel():
    if not current_user.is_admin:
        flash('Only administrators can create new channels')
        return redirect(url_for('index'))
        
    channel = request.form.get('channel')
    if channel and chat_manager.create_channel(channel):
        return redirect(url_for('chat', channel=channel))
    flash('Invalid channel name or channel already exists')
    return redirect(url_for('index'))

@app.route('/upload', methods=['POST'])
@login_required
def upload_file():
    if 'file' not in request.files:
        return 'No file part', 400
    file = request.files['file']
    if not file or file.filename == '':
        return 'No selected file', 400
    
    filename = file.filename
    if filename is None:
        return 'Invalid filename', 400
        
    if allowed_file(filename):
        safe_filename = secure_filename(filename)
        if not safe_filename:
            return 'Invalid filename', 400
        file.save(os.path.join(app.config['UPLOAD_FOLDER'], safe_filename))
        return {'filename': safe_filename, 'url': f'/static/uploads/{safe_filename}'}, 200
    return 'Invalid file type', 400

@socketio.on('join')
def on_join(data):
    if not current_user.is_authenticated:
        return
    channel = data['channel']
    join_room(channel)
    chat_manager.add_user_to_channel(channel, current_user.username)
    emit('status', {'msg': f'{current_user.username} has joined the channel'}, to=channel)
    broadcast_user_list(channel)

@socketio.on('leave')
def on_leave(data):
    if not current_user.is_authenticated:
        return
    channel = data['channel']
    leave_room(channel)
    chat_manager.remove_user_from_channel(channel, current_user.username)
    emit('status', {'msg': f'{current_user.username} has left the channel'}, to=channel)
    broadcast_user_list(channel)

@socketio.on('typing')
def handle_typing(data):
    if not current_user.is_authenticated:
        return
    channel = data['channel']
    is_typing = data['typing']
    emit('typing_status', {
        'username': current_user.username,
        'typing': is_typing
    }, to=channel)

@socketio.on('message')
def handle_message(data):
    if not current_user.is_authenticated:
        return
    channel = data['channel']
    msg = emoji.emojize(data['msg']) if data.get('type') == 'text' else data['msg']
    
    # Store message in database
    message = Message(
        content=msg,
        channel=channel,
        user_id=current_user.id,
        message_type=data.get('type', 'text')
    )
    db.session.add(message)
    db.session.commit()
    
    emit('message', {
        'msg': msg,
        'username': current_user.username,
        'type': data.get('type', 'text'),
        'message_id': message.id
    }, to=channel)

@socketio.on('reaction')
def handle_reaction(data):
    if not current_user.is_authenticated:
        return
    message_id = data.get('message_id')
    emoji_reaction = data.get('emoji')
    channel = data.get('channel')
    
    reaction = MessageReaction.query.filter_by(
        message_id=message_id,
        user_id=current_user.id,
        emoji=emoji_reaction
    ).first()
    
    if reaction:
        db.session.delete(reaction)
        db.session.commit()
        action = 'remove'
    else:
        new_reaction = MessageReaction()
        new_reaction.message_id = message_id
        new_reaction.user_id = current_user.id
        new_reaction.emoji = emoji_reaction
        db.session.add(new_reaction)
        db.session.commit()
        action = 'add'
    
    reactions = MessageReaction.query.filter_by(message_id=message_id).all()
    reaction_counts = {}
    for r in reactions:
        reaction_counts[r.emoji] = reaction_counts.get(r.emoji, 0) + 1
    
    emit('reaction_update', {
        'message_id': message_id,
        'reactions': reaction_counts,
        'action': action,
        'emoji': emoji_reaction,
        'username': current_user.username
    }, to=channel)

if not os.path.exists(app.config['UPLOAD_FOLDER']):
    os.makedirs(app.config['UPLOAD_FOLDER'])

with app.app_context():
    db.create_all()
