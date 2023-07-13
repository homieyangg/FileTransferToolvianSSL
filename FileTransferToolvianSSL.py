import codecs
import configparser
import datetime
import os
import multiprocessing
import threading
from tkinter import *
from tkinter import Tk, Label, Button, Text, Scrollbar, END, filedialog, ttk, font
import paramiko

log_file_path = 'log.txt'


def create_log_file():
    with open(log_file_path, 'w') as file:
        file.write('Log File\n')


root = Tk()
root.title("File Transfer")
root.geometry("900x400")

# 創建自訂字體
custom_font = font.Font(family="微軟正黑體", size=14, weight="bold")

label = Label(root, text="File Transfer Progress")
label.pack()

progress = ttk.Progressbar(root, length=100, mode='determinate')
progress.pack()

frame = Frame(root)
frame.pack(fill=BOTH, expand=True)

scrollbar = Scrollbar(frame)
scrollbar.pack(side=RIGHT, fill=Y)

text_field = Text(frame, height=10, width=50, yscrollcommand=scrollbar.set, font=custom_font)
text_field.pack(fill=BOTH, expand=True)

scrollbar.config(command=text_field.yview)

config_file_name = None
transfer_in_progress = False  # 追蹤程式是否正在運行


def write_log(message, message_type="default"):
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_message = f"[{timestamp}] {message} \n"

    if message_type == "success":
        text_field.tag_config("success", foreground="green")
        text_field.insert(END, log_message, "success")
    elif message_type == "failure":
        text_field.tag_config("failure", foreground="red")
        text_field.insert(END, log_message, "failure")
    elif message_type == "done":
        text_field.tag_config("done", foreground="yellow")
        text_field.insert(END, log_message, "done")
    else:
        text_field.insert(END, log_message)

    text_field.see(END)

    with open(log_file_path, 'a', encoding='utf-8') as file:
        file.write(log_message)


if not os.path.exists(log_file_path):
    create_log_file()


def select_file():
    global config_file_name
    config_file_name = filedialog.askopenfilename()
    label.config(text="Selected File: " + config_file_name)


def start_transfer():
    global transfer_in_progress

    if transfer_in_progress:
        write_log("Transfer is already in progress. Please wait.")
        return

    if config_file_name is not None:
        transfer_in_progress = True
        write_log("Start Copy")
        read_config(config_file_name)
    else:
        write_log("Please select a file first.")


def read_config(config_file_name):
    config = configparser.ConfigParser()
    with codecs.open(config_file_name, 'r', encoding='utf-8') as file:
        config.read_file(file)

    servers = []
    for section in config.sections():
        if section.startswith('Server'):
            server = {
                'ip': config.get(section, 'ip'),
                'username': config.get(section, 'username'),
                'password': config.get(section, 'password')
            }
            servers.append(server)

    paths = []
    for section in config.sections():
        if section.startswith('Paths'):
            for option in config.options(section):
                if option.endswith('_local'):
                    path_name = option[:-6]
                    local_file_path = config.get(section, option).split(',')
                    remote_file_path = config.get(section, f"{path_name}_remote").split(',')

                    backup_option = f"{path_name}_backup_remote"
                    backup_remote_paths = config.get(section, backup_option).split(',') if config.has_option(section,
                                                                                                             backup_option) else []

                    path = {
                        'local': local_file_path,
                        'remote': remote_file_path,
                        'backup_remote': backup_remote_paths
                    }
                    paths.append(path)

    total_files = multiprocessing.Value('i', 0)
    for path in paths:
        for local_path in path['local']:
            for dirpath, dirnames, filenames in os.walk(local_path):
                total_files.value += len(filenames)
    progress['maximum'] = total_files.value

    def done_message():
        global transfer_in_progress
        transfer_in_progress = False
        write_log("Done", message_type="done")

    def worker(server, counter, done_files):
        try:
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            ssh.connect(server['ip'], username=server['username'], password=server['password'])
            sftp = ssh.open_sftp()

            for path in paths:
                local_paths = path['local']
                remote_paths = path['remote']
                backup_remote_paths = path['backup_remote']

                for i in range(len(local_paths)):
                    local_folder_path = local_paths[i]
                    remote_folder_path = remote_paths[i]

                    if backup_remote_paths and backup_remote_paths[i]:
                        backup_remote_path = backup_remote_paths[i]
                        now = datetime.datetime.now()
                        date_string = now.strftime("%Y%m%d%H%M%S")
                        backup_remote_folder = os.path.normpath(os.path.join(backup_remote_path, date_string))
                        remote_folder_path_t = remote_folder_path.replace('/', '\\').strip('\\')
                        backup_command = f"xcopy /E /I {remote_folder_path_t} {backup_remote_folder}"
                        ssh.exec_command(backup_command)

                    file_paths = []
                    for root, dirs, files in os.walk(local_folder_path):
                        for file in files:
                            file_path = os.path.join(root, file)
                            file_paths.append(file_path)

                    ignore_files = []
                    if config.has_option(section, 'ignore_file'):
                        ignore_files = config.get(section, 'ignore_file').split(',')

                    for file_path in file_paths:
                        file_name = os.path.basename(file_path)

                        if file_name in ignore_files:
                            write_log(f"Ignoring file: {file_path}")
                            continue

                        relative_path = os.path.relpath(file_path, local_folder_path)
                        remote_file_path = os.path.join(remote_folder_path, relative_path)

                        if os.path.isdir(file_path):
                            sftp.mkdir(remote_file_path)
                        else:
                            sftp.put(file_path, remote_file_path)

                        with done_files.get_lock():
                            done_files.value += 1
                        progress['value'] = done_files.value

                        # write_log(f"Copying file in {server['ip']}: {file_path}")

            sftp.close()
            ssh.close()
            write_log(f"Successfully copied files to server {server['ip']}", message_type="success")
        except Exception as e:
            stderr_str = str(e)
            if stderr_str:
                write_log(stderr_str, message_type="failure")

        with counter.get_lock():
            counter.value += 1
            if counter.value == len(servers):
                done_message()

    counter = multiprocessing.Value('i', 0)
    done_files = multiprocessing.Value('i', 0)

    for server in servers:
        threading.Thread(target=worker, args=(server, counter, done_files)).start()


text_field.tag_configure("success", foreground="green")
text_field.tag_configure("failure", foreground="red")
text_field.tag_configure("done", foreground="yellow")

Button(root, text="Select File", command=select_file).pack()
Button(root, text="Start", command=start_transfer).pack()

root.mainloop()
