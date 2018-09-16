from flask import session, jsonify, request, abort
from flask_restplus import Namespace, Resource

from CTFd.models import db, Challenges, Unlocks, Fails, Solves, Teams, Flags
from CTFd.utils import config
from CTFd.utils import user as current_user
from CTFd.utils.user import get_current_team
from CTFd.utils.user import get_current_user
from CTFd.plugins.challenges import get_chal_class
from CTFd.utils.dates import ctf_started, ctf_ended, ctf_paused, ctftime
from CTFd.utils.decorators import (
    admins_only,
    during_ctf_time_only,
    require_verified_emails,
    viewable_without_authentication
)
from sqlalchemy.sql import or_

import logging
import time

submissions_namespace = Namespace('submissions', description="Endpoint to retrieve Submission")


@submissions_namespace.route('')
class SubmissionsList(Resource):
    @admins_only
    def get(self):
        pass

    @during_ctf_time_only
    @viewable_without_authentication()
    def post(self):
        request_json = request.get_json() or {}
        request_form = request.form

        challenge_id = request.form.get('challenge_id') or request_json.get('challenge_id')
        user_id = session['id']

        if ctf_paused():
            return {
                'status': 3,
                'message': '{} is paused'.format(config.ctf_name())
            }, 403

        if (current_user.authed() and current_user.is_verified() and (
                ctf_started() or config.view_after_ctf())) or current_user.is_admin():
            user = get_current_user()
            team = get_current_team()

            fails = Fails.query.filter_by(
                user_id=user_id,
                challenge_id=challenge_id
            ).count()
            logger = logging.getLogger('Flags')
            data = (
            time.strftime("%m/%d/%Y %X"), session['username'].encode('utf-8'), request.form['key'].encode('utf-8'),
            current_user.get_wrong_submissions_per_minute(session['id']))
            print("[{0}] {1} submitted {2} with kpm {3}".format(*data))

            chal = Challenges.query.filter_by(id=challenge_id).first_or_404()
            if chal.hidden:
                abort(404)
            chal_class = get_chal_class(chal.type)

            # Anti-bruteforce / submitting Flags too quickly
            if current_user.get_wrong_submissions_per_minute(session['id']) > 10:
                if ctftime():
                    chal_class.fail(
                        user=user,
                        team=team,
                        challenge=chal,
                        request=request
                    )
                logger.warn("[{0}] {1} submitted {2} with kpm {3} [TOO FAST]".format(*data))
                # return '3' # Submitting too fast
                return {
                    'status': 3,
                    'message': "You're submitting Flags too fast. Slow down."
                }, 403

            solves = Solves.query.filter_by(
                user_id=user_id,
                challenge_id=challenge_id
            ).first()

            # Challange not solved yet
            if not solves:
                provided_key = request.form['key'].strip()
                saved_Flags = Flags.query.filter_by(challenge_id=chal.id).all()

                # Hit max attempts
                max_tries = chal.max_attempts
                if max_tries and fails >= max_tries > 0:
                    return {
                        'status': 0,
                        'message': "You have 0 tries remaining"
                    }, 403

                status, message = chal_class.attempt(chal, request)
                if status:  # The challenge plugin says the input is right
                    if ctftime() or current_user.is_admin():
                        chal_class.solve(
                            user=user,
                            team=team,
                            challenge=chal,
                            request=request
                        )
                    logger.info("[{0}] {1} submitted {2} with kpm {3} [CORRECT]".format(*data))
                    return {
                        'status': 1,
                        'message': message
                    }
                else:  # The challenge plugin says the input is wrong
                    if ctftime() or current_user.is_admin():
                        chal_class.fail(
                            user=user,
                            team=team,
                            challenge=chal,
                            request=request
                        )
                    logger.info("[{0}] {1} submitted {2} with kpm {3} [WRONG]".format(*data))

                    if max_tries:
                        attempts_left = max_tries - fails - 1  # Off by one since fails has changed since it was gotten
                        tries_str = 'tries'
                        if attempts_left == 1:
                            tries_str = 'try'
                        if message[-1] not in '!().;?[]\{\}':  # Add a punctuation mark if there isn't one
                            message = message + '.'
                        return {
                            'status': 0,
                            'message': '{} You have {} {} remaining.'.format(message, attempts_left, tries_str)
                        }
                    else:
                        return {
                            'status': 0,
                            'message': message
                        }

            # Challenge already solved
            else:
                logger.info("{0} submitted {1} with kpm {2} [ALREADY SOLVED]".format(*data))
                return {
                    'status': 2,
                    'message': 'You already solved this'
                }
        else:
            return {
                'status': -1,
                'message': "You must be logged in to solve a challenge"
            }, 302