import os
import base64
import urllib.parse

from typing import Callable

from flask import Flask, flash, render_template, send_from_directory, request, url_for, redirect

from passlib.hash import bcrypt_sha256
from sqlalchemy import update

from models import engine, Users, Teams, session_factory, Base, Pages
from utils import verify_hcaptcha, generate_password, send_email, generate_username, valid_symbols
from forms import CaptainRegister, TeamRegister

app = Flask("quiz-tournament-registration")
app.secret_key = os.getenv('SECRET_KEY')

Base.metadata.create_all(engine)


@app.route('/favicon.ico')
def favicon():
    return send_from_directory(os.path.join(app.root_path, 'static'),
                               'favicon.ico', mimetype='image/vnd.microsoft.icon')


@app.route('/success')
def success():
    return render_template('success.html',
                           message=f'Регистрация прошла успешно! Письмо с дальнейшей инструкцией отправлено на Вашу '
                                   f'почту. Иногда оно попадает в спам, потому советуем проверить этот раздел. '
                                   f'При возникновении проблем обращайтесь в беседу для обратной связи.')


@app.errorhandler(404)
def page_not_found(e):
    return render_template('error.html', message='Страница не найдена'), 404


@app.errorhandler(403)
def page_not_found(e):
    return render_template('error.html', message='Доступ запрещен'), 403


@app.errorhandler(500)
def page_not_found(e):
    return render_template('error.html', message='Ошибка сервера'), 500


@app.route('/', methods=['GET', 'POST'])
def home():
    return render_template('home.html', message=f'Научим искать любую информацию и отвечать на самые трудные вопросы. '
                                                f'Вам понадобится только поисковая строка браузера, дополненная '
                                                f'собственной смекалкой.')


@app.route('/register-captain', methods=['GET', 'POST'])
def register_captain():
    form = CaptainRegister()
    captcha = request.form.get("g-recaptcha-response")
    result_captcha = verify_hcaptcha(captcha)

    if form.validate_on_submit():
        result_username = valid_symbols(form.username.data)
        result_full_name = valid_symbols(form.full_name.data)
        if result_username and result_full_name:
            with session_factory() as session:
                valid_name = session.query(Users).filter_by(name=form.username.data).first()
                valid_email = session.query(Users).filter_by(email=form.email.data).first()
                if not valid_email and not valid_name and result_captcha:

                    password = generate_password()
                    hashed_password = bcrypt_sha256.hash(str(password))

                    user = Users(
                        name=form.username.data,
                        password=hashed_password,
                        email=form.email.data,
                        website=form.website.data,
                        type="user"
                    )
                    __data = Pages(
                        username=form.username.data,
                        full_name=form.full_name.data,
                        email=form.email.data,
                        data=password
                    )

                    session.add(user)
                    session.add(__data)
                    session.commit()

                    username = base64.b64encode(urllib.parse.quote_plus(form.username.data).encode()).decode()
                    email = base64.b64encode(form.email.data.encode()).decode()

                    return redirect(url_for('create_team', username=username, email=email))
                elif valid_email:
                    flash("Пользователь с такой почтой уже существует!")
                elif valid_name:
                    flash("Пользователь с таким ником уже существует!")
                else:
                    flash("Пройдите каптчу!")
        else:
            flash("Введите корректные символы (поле ввода может содержать только буквы, цифры, и символы @/./+/-/_)")
    return render_template('register_captain.html', form=form)


@app.route('/create_team/<username>/<email>', methods=['GET', 'POST'])
def create_team(username: base64, email: base64):
    form = TeamRegister()
    captcha = request.form.get("g-recaptcha-response")
    result_captcha = verify_hcaptcha(captcha)

    dec_username = urllib.parse.unquote_plus(base64.b64decode(username).decode())

    if form.validate_on_submit():
        result_team_name = valid_symbols(form.team_name.data)
        result_team_city = valid_symbols(form.team_city.data)
        result_team_affiliation = valid_symbols(form.team_affiliation.data)

        if result_team_city and result_team_name and result_team_affiliation:
            with session_factory() as session:
                query = session.query(Users).filter_by(name=dec_username).first()
                if query:
                    captain = query.id
                    no_team = query.team_id

                valid_team_name = session.query(Teams).filter_by(name=form.team_name.data).first()
                if not valid_team_name and not no_team and result_captcha:

                    hashed_password = bcrypt_sha256.hash(str(generate_password()))
                    team_affiliation: Callable[[str], str | None] = lambda aff: aff if aff else None

                    team = Teams(
                        name=form.team_name.data,
                        country=form.team_city.data,
                        affiliation=team_affiliation(form.team_affiliation.data),
                        password=hashed_password,
                        captain_id=captain
                    )

                    session.add(team)
                    session.commit()

                    admin_update = update(Users).values(team_id=team.id).where(Users.id == captain)
                    tmp_team_id = team.id
                    session.execute(admin_update)
                    session.commit()

                    team_name = base64.b64encode(urllib.parse.quote_plus(form.team_name.data).encode()).decode()

                    return redirect(url_for('add_users', team_id=tmp_team_id, team_name=team_name, email=email))
                elif valid_team_name:
                    flash("Команда с таким названием уже существует!")
                elif not result_captcha:
                    flash("Пройдите каптчу!")
                else:
                    flash("Неизвестная ошибка, попробуйте еще раз...")
        else:
            flash("Введите корректные символы (поле ввода может содержать только буквы, цифры, и символы @/./+/-/_)")
    return render_template('create_team.html', form=form)


@app.route('/add_users/<team_id>/<team_name>/<email>', methods=['GET', 'POST'])
def add_users(team_id: int, email: base64, team_name: base64):
    if request.method == 'POST':
        captcha = request.form.get("g-recaptcha-response")
        result_captcha = verify_hcaptcha(captcha)

        user_email_list = request.form.getlist('participant_email[]')
        user_full_name_list = request.form.getlist('participant_full_name[]')

        dec_email = base64.b64decode(email).decode()
        dec_team_name = urllib.parse.unquote_plus(base64.b64decode(team_name).decode())

        valid_email_flag = True
        valid_unique_emails = True

        with session_factory() as session:
            query_user = session.query(Users).filter_by(email=dec_email).first()
            query_team = session.query(Teams).filter_by(name=dec_team_name).first()
            query_count_in_team = session.query(Users).filter_by(team_id=query_team.id).count()

            if query_user and query_team:
                if len(set(user_email_list)) == len(user_email_list) and query_count_in_team + len(
                        user_email_list) <= 5:

                    valid_sym = True
                    for user in range(len(user_email_list)):
                        result_valid_symbols = valid_symbols(user_full_name_list[user])
                        if not result_valid_symbols:
                            valid_sym = False

                    if valid_sym:
                        for user in range(len(user_email_list)):
                            valid_email = session.query(Users).filter_by(email=user_email_list[user]).first()
                            if valid_email:
                                valid_email_flag = False
                                flash(f"Пользователь с почтой {valid_email.email} уже существует!")
                    else:
                        flash(
                            "Введите корректные символы (поле ввода может содержать только буквы, цифры, и символы @/./+/-/_)")

                else:
                    valid_unique_emails = False
                    flash("Введите уникальные имейлы!")
            else:
                valid_email_flag = False
                flash("Неизвестная ошибка, попробуйте еще раз...")

            if valid_unique_emails and valid_email_flag and result_captcha:
                for user in range(len(user_email_list)):
                    username = generate_username()
                    password = generate_password()
                    hashed_password = bcrypt_sha256.hash(str(password))

                    query = Users(
                        name=username,
                        email=user_email_list[user],
                        password=hashed_password,
                        team_id=team_id,
                    )

                    __data = Pages(
                        username=username,
                        full_name=user_full_name_list[user],
                        email=user_email_list[user],
                        data=password
                    )

                    session.add(query)
                    session.add(__data)
                    session.commit()

                context = {'captain_email': dec_email, 'users_list': user_email_list, 'team_name': dec_team_name}
                send_email(recipient=dec_email, context=context, selection=True)

                return redirect(url_for('success'))
            elif not result_captcha:
                flash('Пройдите каптчу!')

    return render_template('add_users.html')


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0')
