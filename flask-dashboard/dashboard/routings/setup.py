from flask import session, request, render_template

from dashboard import blueprint, config, user_app
from dashboard.database.endpoint import get_monitor_rule, update_monitor_rule, get_last_accessed_times
from dashboard.database.monitor_rules import reset_monitor_endpoints
from dashboard.database.tests import get_tests, reset_run, update_test, add_test_result, get_results
from dashboard.database.tests import get_line_results, get_res_current
from dashboard.database.settings import get_setting, set_setting
from dashboard.forms import MonitorDashboard, ChangeSetting, RunTests
from dashboard.measurement import track_performance
from dashboard.security import secure
from unittest import TestLoader

import datetime
import time
import pygal


@blueprint.route('/settings', methods=['GET', 'POST'])
@secure
def settings():
    form = ChangeSetting()
    form.username.data = get_setting('username', 'admin')
    old_password = get_setting('password', 'admin')
    old_password = 'x' * len(old_password)

    if request.method == 'POST' and form.validate():
        set_setting('username', form.username.data)
        if form.password.data:
            set_setting('password', form.password.data)

    return render_template('settings.html', link=config.link, session=session, curr=4, version=config.version,
                           database_name=config.database_name, group=config.get_group_by(), form=form,
                           testDir=config.test_dir, old_password=old_password)


@blueprint.route('/rules', methods=['GET', 'POST'])
@secure
def rules():
    form = MonitorDashboard()
    values = {}
    all_rules = user_app.url_map.iter_rules()

    if request.method == 'POST' and form.validate():
        # Remove the monitor endpoints from the database
        reset_monitor_endpoints()

        for rule in user_app.url_map.iter_rules():
            # Remove existing wrappers
            original = getattr(user_app.view_functions[rule.endpoint], 'original', None)
            if original:
                user_app.view_functions[rule.endpoint] = original

        # request.form only contains checkboxes that are checked
        for data in request.form:
            if data.startswith('checkbox-'):
                endpoint = data.rsplit('-', 1)[1]
                update_monitor_rule(endpoint, value=True)
                rule = get_monitor_rule(endpoint)
                # Add wrappers to the existing functions
                user_app.view_functions[rule.endpoint] = track_performance(user_app.view_functions[rule.endpoint],
                                                                           rule.endpoint)

    # store the result from the database in values (used for rendering)
    for rule in user_app.url_map.iter_rules():
        values[rule.endpoint] = get_monitor_rule(rule.endpoint).monitor

    la = get_last_accessed_times()

    # filter dashboard rules
    all_rules = [r for r in all_rules if not r.rule.startswith('/' + config.link)
                 and not r.rule.startswith('/static-' + config.link)]

    return render_template('rules.html', link=config.link, curr=1, rules=all_rules, access=la, form=form, session=session,
                           values=values)


@blueprint.route('/testmonitor', methods=['GET', 'POST'])
@secure
def testmonitor():
    form = RunTests()
    if request.method == 'POST' and form.validate():
        test_names = []
        reset_run()
        for data in request.form:
            if data.startswith('checkbox-'):
                name = data.rsplit('-', 1)[1]
                test_names.append(name)
                update_test(name, True, datetime.datetime.now(), None)

        suites = TestLoader().discover(config.test_dir, pattern="*test*.py")
        for suite in suites:
            for case in suite:
                for test in case:
                    if str(test) in test_names:
                        result = None
                        time1 = time.time()
                        result = test.run(result)
                        time2 = time.time()
                        update_test(str(test), True, datetime.datetime.now(), result.wasSuccessful())
                        t = (time2 - time1) * 1000
                        add_test_result(str(test), t, datetime.datetime.now(), config.version)

    # Let's render a bar chart, if there is data:
    data = get_line_results()
    times_data = None
    if data:
        times_chart = pygal.HorizontalBar(height=100+len(data)*30)
        times_chart.x_labels = []
        list_avg = []
        list_min = []
        list_max = []
        list_count = []
        for d in data:
            times_chart.x_labels.append(d.version)
            list_min.append(d.min)
            list_avg.append(d.avg)
            list_max.append(d.max)
            list_count.append(d.count)
        times_chart.add('Minimum', list_min, formatter=lambda x: '%.2f ms' % x)
        times_chart.add('Average', list_avg, formatter=lambda x: '%.2f ms' % x)
        times_chart.add('Maximum', list_max, formatter=lambda x: '%.2f ms' % x)
        times_data = times_chart.render_data_uri()

    return render_template('testmonitor.html', link=config.link, session=session, curr=3, form=form, tests=get_tests(),
                           results=get_results(), res_current_version=get_res_current(config.version),
                           times_data=times_data)