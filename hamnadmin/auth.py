#
# Django module to support postgresql.org community authentication 2.0
#
# The main location for this module is the pgweb git repository hosted
# on git.postgresql.org - look there for updates.
#
# To integrate with django, you need the following:
# * Make sure the view "login" from this module is used for login
# * Map an url somwehere (typicall /auth_receive/) to the auth_receive
#   view.
# * In settings.py, set AUTHENTICATION_BACKENDS to point to the class
#   AuthBackend in this module.
# * (And of course, register for a crypto key with the main authentication
#   provider website)
#

from django.http import HttpResponseRedirect
from django.contrib.auth.models import User
from django.contrib.auth.backends import ModelBackend
from django.contrib.auth import login as django_login
from django.contrib.auth import logout as django_logout
from django.conf import settings

import base64
import urlparse
from urllib import quote_plus
from Crypto.Cipher import AES
import time

class AuthBackend(ModelBackend):
	# We declare a fake backend that always fails direct authentication -
	# since we should never be using direct authentication in the first place!
	def authenticate(self, username=None, password=None):
		raise Exception("Direct authentication not supported")


####
# Two regular django views to interact with the login system
####

# Handle login requests by sending them off to the main site
def login(request):
	if request.GET.has_key('next'):
		return HttpResponseRedirect("%s?su=%s" % (
				settings.PGAUTH_REDIRECT,
				quote_plus(request.GET['next']),
				))
	else:
		return HttpResponseRedirect(settings.PGAUTH_REDIRECT)

# Handle logout requests by logging out of this site and then
# redirecting to log out from the main site as well.
def logout(request):
	if request.user.is_authenticated():
		django_logout(request)
	return HttpResponseRedirect("%slogout/" % settings.PGAUTH_REDIRECT)

# Receive an authentication response from the main website and try
# to log the user in.
def auth_receive(request):
	if request.GET.has_key('s') and request.GET['s'] == "logout":
		# This was a logout request
		return HttpResponseRedirect('/')

	if not request.GET.has_key('i'):
		raise Exception("Missing IV")
	if not request.GET.has_key('d'):
		raise Exception("Missing data!")

	# Set up an AES object and decrypt the data we received
	decryptor = AES.new(base64.b64decode(settings.PGAUTH_KEY),
						AES.MODE_CBC,
						base64.b64decode(str(request.GET['i']), "-_"))
	s = decryptor.decrypt(base64.b64decode(str(request.GET['d']), "-_")).rstrip(' ')

	# Now un-urlencode it
	try:
		data = urlparse.parse_qs(s, strict_parsing=True)
	except ValueError, e:
		raise Exception("Invalid encrypted data received.")

	# Check the timestamp in the authentication
	if (int(data['t'][0]) < time.time() - 10):
		raise Exception("Authentication token too old.")

	# Update the user record (if any)
	try:
		user = User.objects.get(username=data['u'][0])
		# User found, let's see if any important fields have changed
		changed = False
		if user.first_name != data['f'][0]:
			user.first_name = data['f'][0]
			changed = True
		if user.last_name != data['l'][0]:
			user.last_name = data['l'][0]
			changed = True
		if user.email != data['e'][0]:
			user.email = data['e'][0]
			changed= True
		if changed:
			user.save()
	except User.DoesNotExist, e:
		# User not found, create it!
		user = User(username=data['u'][0],
					first_name=data['f'][0],
					last_name=data['l'][0],
					email=data['e'][0],
					password='setbypluginnotasha1',
					)
		user.save()

	# Ok, we have a proper user record. Now tell django that
	# we're authenticated so it persists it in the session. Before
	# we do that, we have to annotate it with the backend information.
	user.backend = "%s.%s" % (AuthBackend.__module__, AuthBackend.__name__)
	django_login(request, user)

	# Finally, redirect the user
	if data.has_key('su'):
		return HttpResponseRedirect(data['su'][0])
	# No redirect specified, see if we have it in our settings
	if hasattr(settings, 'PGAUTH_REDIRECT_SUCCESS'):
		return HttpResponseRedirect(settings.PGAUTH_REDIRECT_SUCCESS)
	raise Exception("Authentication successful, but don't know where to redirect!")
