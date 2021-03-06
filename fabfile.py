import os.path
from getpass import getpass
from collections import OrderedDict

from fabric.api import sudo, run, cd, prefix, settings, task, env, prompt, shell_env
from fabric.contrib.console import confirm
from fabric.contrib.files import exists, upload_template, contains

env.hosts = ['vergeev@meetup-bot.me']

PROJECT_FOLDER = '/var/www/meetup-facebook-bot'  # must not end with '/'
PERMANENT_PROJECT_FOLDER = "%s.permanent" % PROJECT_FOLDER
REPOSITORY_URL = 'https://github.com/Stark-Mountain/meetup-facebook-bot.git'
UWSGI_SERVICE_NAME = 'meetup-facebook-bot.service'
SOCKET_PATH = '/tmp/meetup-facebook-bot.socket'
INI_FILE_PATH = os.path.join(PERMANENT_PROJECT_FOLDER, 'meetup-facebook-bot.ini')
VENV_FOLDER = 'venv'
VENV_BIN_DIRECTORY = os.path.join(PERMANENT_PROJECT_FOLDER, VENV_FOLDER, 'bin')
DHPARAM_PATH = '/etc/ssl/certs/dhparam.pem'
SSL_PARAMS_PATH = '/etc/nginx/snippets/ssl-params.conf'
LOG_PATH = '/var/log/meetup-facebook-bot'


def install_python():
    sudo('apt-get update')
    sudo('apt-get install python3-pip python3-dev python3-venv')


def fetch_sources_from_repo(branch, code_directory):
    if exists(code_directory):
        print('Removing the following directory: %s' % code_directory)
        sudo('rm -rf %s' % code_directory)
    git_clone_command = 'git clone {1} {2} --branch {0} --single-branch'
    sudo(git_clone_command.format(branch, REPOSITORY_URL, code_directory))


def reinstall_venv():
    with cd(PERMANENT_PROJECT_FOLDER):
        sudo('rm -rf %s' % VENV_FOLDER)
        sudo('python3 -m venv %s' % VENV_FOLDER)


def install_modules():
    requirements_path = os.path.join(PROJECT_FOLDER, 'requirements.txt')
    venv_activate_path = os.path.join(VENV_BIN_DIRECTORY, 'activate')
    with prefix('source %s' % venv_activate_path):
        sudo('pip install wheel')
        sudo('pip install -r %s' % requirements_path)


def install_nginx():
    sudo('apt-get update')
    sudo('apt-get install nginx')


def install_postgres():
    sudo('apt-get update')
    sudo('apt-get install postgresql postgresql-contrib')


def setup_ufw():
    sudo('ufw allow "Nginx Full"')
    sudo('ufw allow OpenSSH')
    sudo('echo "y" | ufw enable')


def setup_postgres(username, database_name):
    with settings(warn_only=True):
        sudo('sudo -u postgres createuser %s -s' % username)
        sudo('sudo -u postgres createdb %s' % database_name)
    return 'postgresql://%s@/%s' % (username, database_name)


def empty_database(database_name):
    sudo('sudo -u postgres dropdb %s' % database_name)
    sudo('sudo -u postgres createdb %s' % database_name)


def start_letsencrypt_setup():
    sudo("mkdir -p /tmp/git")
    sudo("rm -rf /tmp/git/letsencrypt")
    with cd("/tmp/git"):
        sudo("git clone https://github.com/letsencrypt/letsencrypt")
    with cd("/tmp/git/letsencrypt"):
        sudo('./letsencrypt-auto certonly --standalone')
    sudo('rm -rf /tmp/git')


def start_systemctl_service(service_name):
    sudo('systemctl daemon-reload')
    sudo('systemctl enable %s' % service_name)
    sudo('systemctl restart %s' % service_name)


def prompt_for_environment_variables(env_vars):
    for env_var, value in env_vars.items():
        if value is None or confirm('%s is set. Change it?' % env_var):
            env_vars[env_var] = prompt('Enter %s:' % env_var)
    return env_vars


@task
def renew_ini_file(database_url=None):
    env_vars = OrderedDict(
        [
            ('DATABASE_URL', None),
            ('PAGE_ID', None),
            ('APP_ID', None),
            ('ACCESS_TOKEN', None),
            ('VERIFY_TOKEN', None),
            ('SECRET_KEY', None),
            ('ADMIN_LOGIN', None),
            ('ADMIN_PASSWORD', None),
        ]
    )
    env_vars['DATABASE_URL'] = database_url
    env_vars = prompt_for_environment_variables(env_vars)
    config_vars = env_vars.copy()
    config_vars['SOCKET_PATH'] = SOCKET_PATH
    upload_template(
        filename='deploy_configs/meetup-facebook-bot.ini',
        destination=INI_FILE_PATH,
        context=config_vars,
        use_sudo=True
    )
    env.env_vars = env_vars


def create_permanent_folder():
    with settings(warn_only=True):
        sudo('mkdir %s' % PERMANENT_PROJECT_FOLDER)


def create_log_folder():
    sudo('mkdir -m 777 -p %s' % LOG_PATH)


def create_service_file():
    service_file_config = {
        'user': env.user,
        'work_dir': PROJECT_FOLDER,
        'env_bin_dir': VENV_BIN_DIRECTORY,
        'uwsgi_path': os.path.join(VENV_BIN_DIRECTORY, 'uwsgi'),
        'app_ini_path': INI_FILE_PATH
    }
    upload_template(
        filename='deploy_configs/meetup-facebook-bot.service',
        destination=os.path.join('/etc/systemd/system/', UWSGI_SERVICE_NAME),
        context=service_file_config,
        use_sudo=True
    )


def create_dhparam_if_necessary():
    if exists(DHPARAM_PATH):
        print('dhparam file exists, skipping this step')
        return
    sudo('openssl dhparam -out %s 2048' % DHPARAM_PATH)


def create_ssl_params_if_necessary():
    create_dhparam_if_necessary()
    if exists(SSL_PARAMS_PATH):
        print('Not creating ssl-params.conf, already exists')
        return
    upload_template(
        filename='deploy_configs/ssl_params',
        destination=SSL_PARAMS_PATH,
        context={'dhparam_path': DHPARAM_PATH},
        use_sudo=True
    )


def configure_letsencrypt_if_necessary():
    create_ssl_params_if_necessary()
    env.letsencrypt_folder = os.path.join('/etc/letsencrypt/live', env.domain_name)
    print('Assuming letsencrypt folder is %s' % env.letsencrypt_folder)
    if exists(env.letsencrypt_folder, use_sudo=True):
        print('letsencrypt folder found, skipping letsencrypt setup')
        return
    start_letsencrypt_setup()


def add_nginx_reload_crontab_job():
    # needed for successful ssl certificate renewal
    job = '0 */12 * * * systemctl restart nginx'
    restart_command = 'echo "%s" | sudo tee --append /etc/crontab' % job
    if contains('/etc/crontab', job, use_sudo=True):
        print('already added restart job to crontab, won\'t add again')
        return
    sudo(restart_command)


def configure_nginx_if_necessary():
    nginx_config_path = os.path.join('/etc/nginx/sites-available', env.domain_name)
    if exists(nginx_config_path):
        print('nginx config found, not creating another one')
    else:
        nginx_config_variables = {
            'source_dir': PROJECT_FOLDER,
            'domain': env.domain_name,
            'ssl_params_path': SSL_PARAMS_PATH,
            'fullchain_path': os.path.join(env.letsencrypt_folder, 'fullchain.pem'),
            'privkey_path': os.path.join(env.letsencrypt_folder, 'privkey.pem'),
            'socket_path': SOCKET_PATH
        }
        upload_template(
            filename='deploy_configs/nginx_config',
            destination=nginx_config_path,
            context=nginx_config_variables,
            use_sudo=True
        )
    nginx_config_alias = os.path.join('/etc/nginx/sites-enabled', env.domain_name)
    sudo('ln -sf %s %s' % (nginx_config_path, nginx_config_alias))


def run_setup_script(script_name, context):
    venv_activate_path = os.path.join(VENV_BIN_DIRECTORY, 'activate')
    venv_activate_command = 'source %s' % venv_activate_path
    with cd(PROJECT_FOLDER), shell_env(**context), prefix(venv_activate_command):
        run('python3 %s' % os.path.join(PROJECT_FOLDER, script_name))


def fill_database_with_example_data():
    database_url = getattr(env, 'env_vars', {}).get('DATABASE_URL')
    context = {'DATABASE_URL': database_url}
    context = prompt_for_environment_variables(context)
    run_setup_script('database_setup.py', context)


def set_start_button():
    access_token = getattr(env, 'env_vars', {}).get('ACCESS_TOKEN')
    context = {'ACCESS_TOKEN': access_token}
    context = prompt_for_environment_variables(context)
    run_setup_script('set_start_button.py', context)


def run_setup_scripts():
    fill_database_with_example_data()
    set_start_button()


@task
def bootstrap(branch='master'):
    env.sudo_password = getpass('Initial value for env.sudo_password: ')
    env.domain_name = prompt('Enter your domain name:', default='meetup_facebook_bot')
    create_permanent_folder()
    create_log_folder()
    install_postgres()
    database_url = setup_postgres(username=env.user, database_name=env.user)
    renew_ini_file(database_url)
    install_python()
    fetch_sources_from_repo(branch, PROJECT_FOLDER)
    reinstall_venv()
    install_modules()
    install_nginx()
    configure_letsencrypt_if_necessary()
    add_nginx_reload_crontab_job()
    configure_nginx_if_necessary()
    setup_ufw()
    start_systemctl_service(UWSGI_SERVICE_NAME)
    start_systemctl_service('nginx')
    run_setup_scripts()
    status()


@task
def deploy(branch='master'):
    update_dependencies = confirm('Update dependencies?')
    print('OK, deploying branch %s' % branch)
    env.sudo_password = getpass('Initial value for env.sudo_password: ')
    fetch_sources_from_repo(branch, PROJECT_FOLDER)
    if update_dependencies:
        reinstall_venv()
        install_modules()
    start_systemctl_service(UWSGI_SERVICE_NAME)
    start_systemctl_service('nginx')
    status()


@task
def status():
    if env.sudo_password is None:
        env.sudo_password = getpass('Initial value for env.sudo_password: ')
    sudo('systemctl status %s' % UWSGI_SERVICE_NAME)


@task
def reset_db():
    env.sudo_password = getpass('Initial value for env.sudo_password: ')
    sudo('systemctl stop %s' % UWSGI_SERVICE_NAME)
    empty_database(database_name=env.user)
    fill_database_with_example_data()
    sudo('systemctl start %s' % UWSGI_SERVICE_NAME)
