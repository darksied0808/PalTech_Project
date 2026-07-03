import subprocess
import os

git_path = r"C:\Users\prasanth.sanapathi\AppData\Local\Programs\Git\cmd\git.exe"

def run_git(args):
    print(f"Running: git {' '.join(args)}")
    res = subprocess.run([git_path] + args, capture_output=True, text=True)
    if res.stdout:
        print(res.stdout)
    if res.stderr:
        print(res.stderr)
    return res.returncode == 0

# Run commands
run_git(["init"])
run_git(["add", "."])
run_git(["commit", "-m", "first commit"])
run_git(["branch", "-M", "main"])
run_git(["remote", "remove", "origin"])
run_git(["remote", "add", "origin", "https://github.com/darksied0808/PalTech_Project.git"])
run_git(["push", "-u", "origin", "main"])
