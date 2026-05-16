FROM nginx:1.27-alpine

# Copy custom nginx config
COPY nginx.conf /etc/nginx/conf.d/default.conf

# Minimal placeholder until Phase 4 React build
RUN echo '<html><body><h1>HomeVideoSearcher</h1><p>UI coming in Phase 4.</p></body></html>' \
    > /usr/share/nginx/html/index.html

EXPOSE 80
