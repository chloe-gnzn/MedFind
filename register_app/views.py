from django.contrib import messages
from django.shortcuts import render, redirect

from login_app.utils import log_activity
from medfind_project.session_auth import ROLE_HOME, SESSION_ROLE, get_account

from .forms import PharmacyRegisterForm, UserRegisterForm


def register_view(request):
    """Register a regular MedFind user."""
    if get_account(request):
        return redirect(ROLE_HOME[request.session[SESSION_ROLE]])

    if request.method == 'POST':
        form = UserRegisterForm(request.POST)
        if form.is_valid():
            user = form.save()
            log_activity('user', user.pk, 'register', f'User {user.email} registered.')
            messages.success(request, 'Account created successfully! You can now log in.')
            return redirect('login')  # Transition back to Login Screen
        messages.error(request, 'Please fix the errors below and try again.')
    else:
        form = UserRegisterForm()

    return render(request, 'register_template/register.html', {
        'form': form,
        'title': 'Create your account',
        'kind': 'user',
    })


def register_pharmacy_view(request):
    """Register a pharmacy (starts as 'pending' until an admin verifies it)."""
    if get_account(request):
        return redirect(ROLE_HOME[request.session[SESSION_ROLE]])

    if request.method == 'POST':
        form = PharmacyRegisterForm(request.POST)
        if form.is_valid():
            pharmacy = form.save()
            log_activity('pharmacy', pharmacy.pk, 'register',
                         f'Pharmacy {pharmacy.business_name} registered.')
            messages.success(
                request,
                'Pharmacy registered! Log in and submit your documents so an admin can verify you.'
            )
            return redirect('pharmacy_login')
        messages.error(request, 'Please fix the errors below and try again.')
    else:
        form = PharmacyRegisterForm()

    return render(request, 'register_template/register.html', {
        'form': form,
        'title': 'Register your pharmacy',
        'kind': 'pharmacy',
    })
