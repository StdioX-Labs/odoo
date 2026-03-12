FROM odoo:18.0

USER root

# Install system packages and Python dependencies
RUN apt-get update && \
    apt-get install -y net-tools iproute2 && \
    pip3 install --no-cache-dir --break-system-packages icalendar && \
    rm -rf /var/lib/apt/lists/*

COPY --chown=odoo:odoo addons/ /mnt/extra-addons/
COPY --chown=odoo:odoo config/odoo.conf /etc/odoo/odoo.conf

USER root

EXPOSE 8069 8072

CMD ["odoo", "--config=/etc/odoo/odoo.conf"]
