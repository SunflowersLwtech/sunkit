---
source: GitHub - lobsters/lobsters: Computing-focused community centered around link aggregation and discussion
url: https://github.com/lobsters/lobsters
final_url: https://github.com/lobsters/lobsters
language: en
fetched_at: 2026-05-04
bytes: 8956
---

# GitHub - lobsters/lobsters: Computing-focused community centered around link aggregation and discussion

> Computing-focused community centered around link aggregation and discussion - lobsters/lobsters

Lobsters is a Rails codebase and uses a SQL (MariaDB in production) backend for the database. The code is open source as part of our commitment to transparency. It's been used to run sister sites, but mostly we want people to be able to understand and improve what's happening on Lobsters itself.

Despite the site being an uber mega cringe ghost town running on a quite sad codebase, at least we have no relation to the self-help guru.

We'd love to have your help. Please see the CONTRIBUTING file for details and dev environment setup. If you have questions, there is usually someone in our chat room who's familiar with the code.

Lobsters is a volunteer project with limited development time and a long time horizon, we hope to be running for decades. So our design philosophy is a little different than a typical commercial product:

* We started with Rails 3.2.2 in 2012, so we have a few dusty corners and places where we don't take advantage of features that were introduced since we started.
* We lean into using Rails features instead of custom code, and we'll write a couple dozen lines of narrow code for a feature rather than add a dependency that might require maintenance.
* We are very reluctant to add new production services and almost entirely unwilling to depend on external services. We take pride in self-hosting from the VPS up, which necessitates reducing the number of moving parts.
* We test to ensure functionality, but testing is a lot lighter for moderator and other non-core features. We're trying to maximize the return on investment of testing rather than minimize errors.
* We're willing to take downtime for big code changes rather than try to make them seamless.
* We have users that are unusually likely to use old, experimental, and even homemade browsers, so we only use CSS in the widely available baseline.
* We don't serve JavaScript to logged-out visitors, we use as little JS as possible for users with a vanilla/jQuery-style of DOM attachment, we are (very slowly) making JS entirely optional for users, and we accept JS for mod features. Keeping JS small and optional helps keep the site fast, and an unusually high proportion of visitors use old, odd, and homebrew browsers. We do not want JavaScript in our build chain, it requires too much maintenance.

Please see CONTRIBUTING.md for setup.

You are free to use this code to start your own sister site because the code is available under a permissive license (3-clause BSD). We welcome bug reports and code contributions that help use improve lobste.rs. As a volunteer project we're reluctant to take on work that's not useful to our site, so please understand if we don't want to adopt your custom feature. These instructions assume you know the basics of web development with Ruby on Rails on a Linux server.

Important: the hard part about starting an online community is not the codebase. A new social site has to solve a chicken-and-egg problem: nobody will want to participate on a new site until other people are participating. Before you start working with the code, make a plan for how you'll reach potential community members and what they'll find engaging about the early days. If you don't attract enough early users to reach a self-sustaining level of activity, the code doesn't matter!

As of February 2025 we have a Zulip-based chat room to discuss the codebase and offer limited support to owners of sister sites like warnings about breaking changes and vulnerability announcements. If you run a site using the codebase, you will benefit from joining.

Setup:

* Fork the repo, clone it to your local computer. You should add lobsters as a git remote so you can continue to pull our changes.
* Edit

  ```
  config/application.rb
  ```

  to put in your site's name and domain name.
* We use a paid service called Hatchbox to set up and deploy the server. Reusing this config will be much easier than Heroku/Render/etc. ...Hatchbox has a clever wizard-style flow for getting started. I'm going to explain what our final settings are rather than try to stay current with the wizard setup. This should be all the info you need, just in a slightly different order.

* Follow the Hatchbox Docs to create an account and connect a Hosting Provider. We use DigitalOcean because I was already familiar with it.
* Create a Cluster, ours is called

  ```
  lobsters
  ```

  . We don't have any Cluster settings customized.
* In your Cluster, create a Server. There's a DO limitation that the server name must match your domain name for them to create a reverse DNS PTR record that you'll need for email. We don't have any Server settings customized.
* When a server is created, check if its IP address is blacklisted for sending email. Email spammers constantly try to create servers on every hosting provider. The providers ban them, but the IP address gets a bad reputation and may be on blocklists when it's assigned to you. Check your server's IP ASAP; it's much easier to delete and recreate than get off the blocklists, especially because outsiders don't have any insight into the internal blocklists of big email providers like Google, Apple, and Microsoft.
* You'll need to create a Database. We use MariaDB in prod but are working to migrate to SQLite.
* Create an App. Running through the Settings sections:

  + Processes: Add a

    ```
    solid_queue
    ```

    process, command

    ```
    bundle exec rails solid_queue:start
    ```

    .
  + Activity: This is logs, nothing to change.
  + Repository: Connect your GitHub repo.
  + Domains & SSL: Add your domain names, include both

    ```
    example.org
    ```

    and

    ```
    www.example.org
    ```

    .
  + Environment:

    ```
    BUNDLE_WITHOUT development:test DATABASE_URL trilogy://[username]:[password]@[1.2.3.4]/lobsters INGRESS_PASSWORD [random generated key] PORT 9000 RACK_ENV production RAILS_ENV production RAILS_LOG_TO_STDOUT true RAILS_MAX_THREADS 10 SECRET_KEY_BASE [random generated key]
    ```

    Search the codebase for uses of the

    ```
    ENV
    ```

    global for more that can be easily configured.
  + Databases: We manage this independently of Hatchbox for historic reasons, see

    ```
    #539
    ```

    .
  + Cron Jobs:

    ```
    expire_page_cache * * * * * script/expire_page_cache script/lobsters-cron */5 * * * * bundle exec script/lobsters-cron
    ```
  + Settings: We have tweaks of production config files and we want those tracked in our git repo. We have rigged up settings to run an (unfortunately) clever hook to update those on deploy, see below.

    Pre-build script:

    ```
    hatchbox/pre-build
    ```

    Custom build script: blank Post-build script: blank Post-deploy script:

    ```
    hatchbox/post-deploy
    ```

    Failed deploy script: blank Caddyfile: copy the text of the file

    ```
    hatchbox/Caddyfile
    ```

    from this repo. As it says, you have to manually paste it in on changes and click 'Update Caddy'.
* Make a deployment with Hatchbox. Whew!

* SSH into your server as the

  ```
  root
  ```

  user to set up the deploy hook.

  ```
  ln -s /home/deploy/lobsters/current/hatchbox/root-deploy.service /etc/systemd/system ln -s /home/deploy/lobsters/current/hatchbox/root-deploy.path /etc/systemd/system systemctl daemon-reload systemctl enable --now root-deploy.service # first backup takes 10ish min systemctl enable --now root-deploy.path
  ```
* Deploy again with Hatchbox to run the hook and finish the server provisioning.
* SSH into your server as the

  ```
  deploy
  ```

  user
  + Run

    ```
    rails credentials:edit
    ```

    to set up credentials there, like you did for development. Use

    ```
    config/credentials.yml.sample
    ```

    for a template. On setup, Rails will give you new random value for

    ```
    secret_key_base
    ```

    and you can use

    ```
    rails secret
    ```

    any time you need to generate another. Never

    ```
    git commit
    ```

    or share your

    ```
    config/credentials.yml.enc
    ```

    or

    ```
    config/master.key
    ```

    .
  + Test your mail config for spamminess.
    Run

    ```
    echo "Test Postfix email, visit scnenic https://example.com" | mail -s "Postfix Test" test-whatever@srv1.mailtester.com
    ```
  + Run

    ```
    rails console
    ```

    and create a

    ```
    User
    ```

    for yourself, set

    ```
    is_admin = true
    ```

    . You'll probably also have to create a

    ```
    Category
    ```

    and one

    ```
    Tag
    ```

    for the site to run at all.
  + See logs in

    ```
    ~deploy/sitename/shared/log
    ```

    .
* Run

If everything worked, you should have a running instance now.

Basic moderation happens on-site, but some administrative tasks require use of the rails console in production.
Administrators can create and edit tags at

```
/tags
```

, the mod dashboard is at

```
/mod
```

.
