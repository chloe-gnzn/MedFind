from django.http import Http404
from django.shortcuts import redirect, render

from medfind_project.session_auth import ROLE_HOME, SESSION_ROLE, get_account

INFO_PAGES = {
    'privacy': {
        'title': 'Privacy Policy',
        'subtitle': 'How MedFind collects and protects account information.',
        'sections': [
            ('What we collect', 'We store only the details needed for your account and experience: your name, email address, phone or contact number, saved favorites, and search history.'),
            ('Pharmacy verification files', 'Business permits and licenses uploaded by pharmacies are used strictly for admin verification and are never shown to general users.'),
            ('Your control', 'You can update your profile details, change your password, remove favorites, or clear your search history anytime from your account.'),
        ],
    },
    'terms': {
        'title': 'Terms of Use',
        'subtitle': 'Guidelines for using MedFind medicine availability and pharmacy listings.',
        'sections': [
            ('Availability information only', 'MedFind helps users check medicine prices, stock status, and pharmacy operating hours. It does not provide medical advice, diagnosis, or prescriptions.'),
            ('Prescription medicines', 'Always consult a licensed physician or pharmacist. Prescription-only medicines require a valid prescription at the pharmacy counter.'),
            ('Pharmacy accuracy', 'Verified pharmacies are responsible for keeping their stock quantities, prices, and operating hours accurate and up to date.'),
        ],
    },
    'security': {
        'title': 'Security',
        'subtitle': 'How accounts, passwords, and pharmacy listings are safeguarded.',
        'sections': [
            ('Password protection', 'All User, Pharmacy, and Admin passwords are stored using Django cryptographic password hashing — never in plain text.'),
            ('Verified pharmacies only', 'Only pharmacies reviewed and approved by a MedFind admin appear in public search results and pharmacy listings.'),
            ('Activity auditing', 'Account logins, password resets, profile edits, inventory updates, and admin verification actions are logged for accountability.'),
        ],
    },
    'contact': {
        'title': 'Contact MedFind',
        'subtitle': 'Get in touch with the MedFind support and onboarding team.',
        'sections': [
            ('For patients and customers', 'Need help finding a medicine or managing your account? Log in to manage your profile, or reach our support team at support@medfind.local.'),
            ('For pharmacies', 'Want your pharmacy listed on MedFind? Register via the Pharmacy Portal, upload your business permit or license, and our admin team will review your submission.'),
            ('Report an issue', 'If a pharmacy listing shows outdated hours or stock details, please email support@medfind.local with the pharmacy name and details.'),
        ],
    },
}


def landing_view(request):
    """Public landing page for general visitors  ->  /"""
    if get_account(request):
        return redirect(ROLE_HOME[request.session[SESSION_ROLE]])
    return render(request, 'landing_template/landing.html')


def info_view(request, slug):
    """Public legal/info pages linked from the landing footer."""
    page = INFO_PAGES.get(slug)
    if page is None:
        raise Http404
    return render(request, 'landing_template/info.html', {'page': page, 'slug': slug})
