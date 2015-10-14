import httpretty
import json

from formspree import settings
from formspree.app import DB
from formspree.forms.helpers import HASH
from formspree.users.models import User
from formspree.forms.models import Form, Submission

from formspree_test_case import FormspreeTestCase

class ArchiveSubmissionsTestCase(FormspreeTestCase):
    @httpretty.activate
    def test_automatically_created_forms(self):
        httpretty.register_uri(httpretty.POST, 'https://api.sendgrid.com/api/mail.send.json')

        # submit a form
        self.client.post('/alice@example.com',
            headers = {'referer': 'http://somewhere.com'},
            data={'name': 'john'}
        )
        query = Form.query.filter_by(host='somewhere.com',
                                     email='alice@example.com')
        self.assertEqual(query.count(), 1)
        form = query.first()

        # this form wasn't confirmed, but it has this first submission already
        self.assertEqual(form.submissions.count(), 1)

        # confirm form
        form.confirmed = True
        DB.session.add(form)
        DB.session.commit()

        # submit again
        self.client.post('/alice@example.com',
            headers = {'referer': 'http://somewhere.com'},
            data={'_replyto': 'johann@gmail.com', 'name': 'johann'}
        )

        # submissions now must be 2
        form = query.first()
        self.assertEqual(form.submissions.count(), 2)

        # submit again
        self.client.post('/alice@example.com',
            headers = {'referer': 'http://somewhere.com'},
            data={'_replyto': 'joh@ann.es', '_next': 'http://google.com',
                  'name': 'johannes', 'message': 'salve!'}
        )
        
        # submissions now must be 3
        form = query.first()
        self.assertEqual(form.submissions.count(), 3)

        # check archived values
        submissions = form.submissions.all()

        self.assertEqual(3, len(submissions))
        self.assertNotIn('message', submissions[1].data)
        self.assertNotIn('_next', submissions[1].data)
        self.assertIn('_next', submissions[0].data)
        self.assertEqual('johann@gmail.com', submissions[1].data['_replyto'])
        self.assertEqual('joh@ann.es', submissions[0].data['_replyto'])
        self.assertEqual('johann', submissions[1].data['name'])
        self.assertEqual('johannes', submissions[0].data['name'])
        self.assertEqual('salve!', submissions[0].data['message'])

        # check if submissions over the limit are correctly deleted
        self.assertEqual(settings.ARCHIVED_SUBMISSIONS_LIMIT, 3)

        self.client.post('/alice@example.com',
            headers = {'referer': 'http://somewhere.com'},
            data={'which-submission-is-this': 'the third!'}
        )
        self.assertEqual(3, form.submissions.count())
        newest = form.submissions.first() # first should be the newest
        self.assertEqual(newest.data['which-submission-is-this'], 'the third!')

        self.client.post('/alice@example.com',
            headers = {'referer': 'http://somewhere.com'},
            data={'which-submission-is-this': 'the fourth!'}
        )
        self.assertEqual(3, form.submissions.count())
        newest, previous, _ = form.submissions.all()
        self.assertEqual(newest.data['which-submission-is-this'], 'the fourth!')
        self.assertEqual(previous.data['which-submission-is-this'], 'the third!')

        #
        # try another form (to ensure that a form is not deleting wrong submissions)
        self.client.post('/sokratis@example.com',
            headers = {'referer': 'http://here.com'},
            data={'name': 'send me the confirmation!'}
        )
        query = Form.query.filter_by(host='here.com',
                                     email='sokratis@example.com')
        self.assertEqual(query.count(), 1)
        secondform = query.first()

        self.assertEqual(secondform.submissions.count(), 1)

        # confirm
        secondform.confirmed = True
        DB.session.add(form)
        DB.session.commit()

        # submit more times and test
        self.client.post('/sokratis@example.com',
            headers = {'referer': 'http://here.com'},
            data={'name': 'leibniz'}
        )

        self.assertEqual(2, secondform.submissions.count())
        self.assertEqual(secondform.submissions.first().data['name'], 'leibniz')

        self.client.post('/sokratis@example.com',
            headers = {'referer': 'http://here.com'},
            data={'name': 'schelling'}
        )

        # in the meantime we got a request from sendgrid saying this email address is invalid or something
        # simulate sendgrid webhook
        self.client.post('/webhooks/sendgrid', data=json.dumps([{
            'email': 'sokratis@example.com',
            'timestamp': 1444830840,
            'smtp-id': '<14c5d75ce93.dfd.64b469@ismtpd-555>',
            'event': 'dropped',
            'category': 'confirmation',
            'form': form.id,
            'host': 'http://here.com',
            'sg_event_id': '8RaVu-zOQFKLm9Gkk8Il-g==',
            'sg_message_id': '14c5d75ce93.dfd.64b469.filter0001.16648.5515E0B88.0',
            'reason': 'Bounced Address',
            'status': '5.0.0'
        }]))
        # but since the form was confirmed this shouldn't do anything.

        self.assertEqual(3, secondform.submissions.count())
        newest, previous, last = secondform.submissions.all()
        self.assertEqual(newest.data['name'], 'schelling')
        self.assertEqual(previous.data['name'], 'leibniz')
        self.assertEqual(last.data['name'], 'send me the confirmation!')

        self.client.post('/sokratis@example.com',
            headers = {'referer': 'http://here.com'},
            data={'name': 'husserl'}
        )

        self.assertEqual(3, secondform.submissions.count())
        newest, previous, last = secondform.submissions.all()
        self.assertEqual(newest.data['name'], 'husserl')
        self.assertEqual(previous.data['name'], 'schelling')
        self.assertEqual(last.data['name'], 'leibniz')

        # now check the previous form again
        newest, previous, _ = form.submissions.all()
        self.assertEqual(newest.data['which-submission-is-this'], 'the fourth!')
        self.assertEqual(previous.data['which-submission-is-this'], 'the third!')

        self.client.post('/alice@example.com',
            headers = {'referer': 'http://somewhere.com'},
            data={'which-submission-is-this': 'the fifth!'}
        )
        self.assertEqual(3, form.submissions.count())
        newest, previous, last = form.submissions.all()
        self.assertEqual(newest.data['which-submission-is-this'], 'the fifth!')
        self.assertEqual(previous.data['which-submission-is-this'], 'the fourth!')
        self.assertEqual(last.data['which-submission-is-this'], 'the third!')

        # just one more time the second form
        self.assertEqual(3, secondform.submissions.count())
        newest, previous, _ = secondform.submissions.all()
        self.assertEqual(newest.data['name'], 'husserl')
        self.assertEqual(previous.data['name'], 'schelling')

    @httpretty.activate
    def test_upgraded_user_access(self):
        httpretty.register_uri(httpretty.POST, 'https://api.sendgrid.com/api/mail.send.json')

        # register user
        r = self.client.post('/register',
            data={'email': 'colorado@springs.com',
                  'password': 'banana'}
        )

        # upgrade user manually
        user = User.query.filter_by(email='colorado@springs.com').first()
        user.upgraded = True
        DB.session.add(user)
        DB.session.commit()

        # create form
        r = self.client.post('/forms',
            headers={'Accept': 'application/json',
                     'Content-type': 'application/json'},
            data=json.dumps({'email': 'hope@springs.com'})
        )
        resp = json.loads(r.data)
        form_endpoint = resp['hashid']

        # manually confirm the form
        form = Form.get_with_hashid(form_endpoint)
        form.confirmed = True
        DB.session.add(form)
        DB.session.commit()
        
        # submit form
        r = self.client.post('/' + form_endpoint,
            headers={'Referer': 'formspree.io'},
            data={'name': 'bruce', 'message': 'hi, my name is bruce!'}
        )

        # test submissions endpoint (/forms/<hashid>/)
        r = self.client.get('/forms/' + form_endpoint + '/',
            headers={'Accept': 'application/json'}
        )
        submissions = json.loads(r.data)['submissions']
        self.assertEqual(len(submissions), 1)
        self.assertEqual(submissions[0]['name'], 'bruce')
        self.assertEqual(submissions[0]['message'], 'hi, my name is bruce!')

        # test exporting feature (both json and csv file downloads)
        r = self.client.get('/forms/' + form_endpoint + '.json')
        submissions = json.loads(r.data)['submissions']
        self.assertEqual(len(submissions), 1)
        self.assertEqual(submissions[0]['name'], 'bruce')
        self.assertEqual(submissions[0]['message'], 'hi, my name is bruce!')

        r = self.client.get('/forms/' + form_endpoint + '.csv')
        lines = r.data.splitlines()
        self.assertEqual(len(lines), 2)
        self.assertEqual(lines[0], 'date,message,name')
        self.assertIn('"hi, my name is bruce!"', lines[1])

        # test submissions endpoint with the user downgraded
        user.upgraded = False
        DB.session.add(user)
        DB.session.commit()
        r = self.client.get('/forms/' + form_endpoint + '/')
        self.assertEqual(r.status_code, 402) # it should fail

        # test submissions endpoint without a logged user
        self.client.get('/logout')
        r = self.client.get('/forms/' + form_endpoint + '/')
        self.assertEqual(r.status_code, 302) # it should return a redirect (via @user_required)

    @httpretty.activate
    def test_deleting_unconfirmed_failed_submissions(self):
        # when the form is not confirmed we still store submissions,
        # but if sendgrid says it couldn't deliver the confirmation email then
        # we don't store it anymore.
        httpretty.register_uri(httpretty.POST, 'https://api.sendgrid.com/api/mail.send.json')

        # submit a form
        self.client.post('/alice@example.com',
            headers = {'referer': 'http://somewhere.com'},
            data={'name': 'john'}
        )
        query = Form.query.filter_by(host='somewhere.com',
                                     email='alice@example.com')
        self.assertEqual(query.count(), 1)
        form = query.first()

        # this form wasn't confirmed, but it has this first submission already
        self.assertEqual(form.submissions.count(), 1)

        # submit again
        self.client.post('/alice@example.com',
            headers = {'referer': 'http://somewhere.com'},
            data={'_replyto': 'johann@gmail.com', 'name': 'johann'}
        )

        # submissions now must be 2
        form = query.first()
        self.assertEqual(form.counter, 2)
        self.assertEqual(form.submissions.count(), 2)

        # got a request from sendgrid saying this email address is invalid or something
        # simulate sendgrid webhook
        self.client.post('/webhooks/sendgrid', data=json.dumps([{
            'email': 'alice@example.com',
            'timestamp': 1444830840,
            'smtp-id': '<14c5d75ce93.dfd.64b469@ismtpd-555>',
            'event': 'dropped',
            'category': 'confirmation',
            'form': form.id,
            'host': 'http://somewhere.com',
            'sg_event_id': '8RaVu-zOQFKLm9Gkk8Il-g==',
            'sg_message_id': '14c5d75ce93.dfd.64b469.filter0001.16648.5515E0B88.0',
            'reason': 'Bounced Address',
            'status': '5.0.0'
        }]))

        # submissions must be 0
        form = query.first()
        self.assertEqual(form.submissions.count(), 0)
