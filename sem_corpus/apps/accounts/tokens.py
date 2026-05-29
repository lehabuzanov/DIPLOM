from django.contrib.auth.tokens import PasswordResetTokenGenerator


class EmailActivationTokenGenerator(PasswordResetTokenGenerator):
    def _make_hash_value(self, user, timestamp):
        return f"{user.pk}{user.password}{user.email}{user.is_active}{timestamp}"


email_activation_token = EmailActivationTokenGenerator()
