# Hosting Blood Network on PythonAnywhere (free)

Result: a link like `https://YOURNAME.pythonanywhere.com` that anyone can open on a phone or laptop.
Replace `YOURNAME` everywhere below with your PythonAnywhere username.

## What you need
- A free "Beginner" account at pythonanywhere.com (no card needed).
- The file `blood-network-hosting.zip` (the project without `venv` and without any database).

## 1. Upload
1. PythonAnywhere -> **Files** tab -> upload `blood-network-hosting.zip` into `/home/YOURNAME/`.
2. **Consoles** tab -> start a **Bash** console and run:
   ```
   unzip blood-network-hosting.zip
   cd blood-network
   ```

## 2. Python environment
Still in the Bash console:
```
python3.13 --version        # if this says "command not found", use python3.12 below instead
python3.13 -m venv ~/bn-venv
source ~/bn-venv/bin/activate
pip install -r requirements.txt
```
(The project needs Python 3.12 or newer.)

## 3. Create the database and accounts
```
python manage.py migrate
python manage.py set_hospital_logins --password "PICK-A-STRONG-PASSWORD-1"
python manage.py createsuperuser
python manage.py collectstatic --noinput
```
- `migrate` also creates the cities, the hospitals and one login per hospital. It prints nine random
  passwords once; ignore them, because `set_hospital_logins` replaces them with the one you chose and
  prints the nine usernames (for example `civilhospital_sukkur`). Write the usernames down.
- Anyone who knows that hospital password can verify requests, so do not post it publicly. For a demo,
  give people ONE hospital username and the password privately.
- `createsuperuser` makes your admin account. Choose a password only you know.
- Do NOT run `seed_demo_data` if you want only real data.

## 4. Create the web app
1. **Web** tab -> **Add a new web app** -> your free `YOURNAME.pythonanywhere.com` domain -> **Manual configuration** -> pick the same Python version as above (3.13 or 3.12).
2. On the Web tab set:
   - **Source code:** `/home/YOURNAME/blood-network`
   - **Virtualenv:** `/home/YOURNAME/bn-venv`
3. Click the **WSGI configuration file** link, delete everything in it, and paste this (change YOURNAME, and
   paste a long random string as the key; make one with
   `python -c "import secrets; print(secrets.token_urlsafe(50))"` in the console):
   ```python
   import os, sys

   path = "/home/YOURNAME/blood-network"
   if path not in sys.path:
       sys.path.insert(0, path)

   os.environ["DJANGO_SETTINGS_MODULE"] = "config.settings"
   os.environ["DJANGO_DEBUG"] = "0"
   os.environ["DJANGO_SECRET_KEY"] = "PASTE-THE-LONG-RANDOM-STRING-HERE"
   os.environ["DJANGO_ALLOWED_HOSTS"] = "YOURNAME.pythonanywhere.com"

   from django.core.wsgi import get_wsgi_application
   application = get_wsgi_application()
   ```
4. Still on the Web tab, under **Static files** add one row:
   - **URL:** `/static/`
   - **Directory:** `/home/YOURNAME/blood-network/staticfiles`
5. Turn on **Force HTTPS**.
6. Press the green **Reload** button, then open `https://YOURNAME.pythonanywhere.com`.

## 5. Check it
- Home page loads with its styling; `/accounts/signup/` lets you create a user.
- Log in as the admin: you land on `/admin-panel/`.
- Log in as a hospital login: you land on the verification desk.
- Open the link on your phone.

## If something is wrong
- **Web tab -> Error log** shows the real reason.
- *Bad Request (400) / DisallowedHost:* `DJANGO_ALLOWED_HOSTS` does not match your address exactly.
- *CSRF verification failed:* the address in `DJANGO_ALLOWED_HOSTS` is wrong, or you opened the site over `http://` instead of `https://`.
- *Page has no styling:* the Static files row is missing or its directory is wrong; run `collectstatic` again and Reload.
- *no such table / no such column:* run `python manage.py migrate` in the Bash console (with `source ~/bn-venv/bin/activate` first).

## Updating later
Upload the new zip, `unzip -o` it over the old folder (never delete `db.sqlite3`; it holds your data),
then in the console: `source ~/bn-venv/bin/activate`, `cd ~/blood-network`, `python manage.py migrate`,
`python manage.py collectstatic --noinput`, and press **Reload** on the Web tab.

## Free-plan notes
- Free accounts ask you to press a button on the Web tab now and then to keep the site up; PythonAnywhere
  emails a reminder first. Check the Web tab before a demo or marking day.
- The site needs no outside internet access (all CSS, JavaScript and fonts are bundled), so the free
  plan's outbound limits do not matter.
- Background commands do not run on the free plan, so `escalate_requests` is not needed there: a hospital
  that misses its deadline is noticed whenever any page or the notification bell loads.
- The database is one SQLite file in the project folder. Back it up by downloading `db.sqlite3` from the Files tab.
