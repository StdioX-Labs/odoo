GOOGLE_FORM_URL = (
    'https://docs.google.com/forms/d/e/1FAIpQLSdvOjRpoAz-C4Mnnbajcq-nAKskgVU94L5fwbuibfAaixpN0Q'
    '/viewform?usp=publish-editor'
)


def migrate(cr, version):
    cr.execute(
        """
        UPDATE custom_appointment_settings
        SET feedback_external_url = %s
        WHERE feedback_external_url IS NULL
           OR feedback_external_url = ''
        """,
        (GOOGLE_FORM_URL,),
    )
