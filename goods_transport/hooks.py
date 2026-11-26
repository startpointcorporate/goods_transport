boot_session = [
	"goods_transport.goods_transport.services.fleet_map.boot_session",
	"goods_transport.goods_transport.services.toll_routing.extend_bootinfo",
	"goods_transport.goods_transport.services.truck_plan.boot_session",
]

app_name = "goods_transport"
app_title = "Goods Transport"
app_publisher = "Techs Arena"
app_description = "Accounting for goods transport"
app_email = "info@techsarena.com"
app_license = "mit"

# Driver payroll links to Salary Component / Salary Structure, so HRMS must be
# installed first. Org-qualified so parse_app_name() resolves locally instead of
# calling the GitHub API.
required_apps = ["frappe/erpnext", "frappe/hrms"]

after_install = "goods_transport.install.after_install"

# Form scripts
doctype_js = {
	"Transport Trip": "public/js/transport_trip.js",
	"Bilty": "public/js/operational_links.js",
	"Proof of Delivery": "public/js/operational_links.js",
	"Trip Advance": "public/js/operational_links.js",
	"Trip Expense": "public/js/operational_links.js",
	"Trip Settlement": "public/js/operational_links.js",
	"Driver": "public/js/driver.js",
	"Vehicle": "public/js/fleet_tyres.js",
}

# Trip lifecycle -> driver earnings + Transport-User sidebar cleanup
inspection_service = "goods_transport.goods_transport.services.trip_inspection"
extend_doctype_class = {"File": [inspection_service + ".InspectionFile"]}
has_permission = {
	"Trip Vehicle Inspection": inspection_service + ".has_permission",
	"File": inspection_service + ".file_permission",
}
permission_query_conditions = {
	"Trip Vehicle Inspection": inspection_service + ".permission_query",
	"File": inspection_service + ".file_permission_query",
}

doc_events = {
	"File": {
		"before_insert": inspection_service + ".protect_file",
		"before_validate": inspection_service + ".protect_file",
		"validate": inspection_service + ".protect_file",
		"on_trash": inspection_service + ".protect_file",
	},
	"Vehicle": {
		"validate": "goods_transport.goods_transport.services.fleet_odometer.validate_vehicle",
	},
	"Asset Maintenance Log": {
		"on_submit": "goods_transport.goods_transport.doctype.vehicle_maintenance_schedule.vehicle_maintenance_schedule.complete_asset_task",
		"before_cancel": "goods_transport.goods_transport.doctype.vehicle_maintenance_schedule.vehicle_maintenance_schedule.prevent_asset_completion_cancel",
	},
	"Vehicle Log": {
		"before_submit": "goods_transport.goods_transport.services.fleet_odometer.validate_vehicle_log_on_submit",
		"before_cancel": "goods_transport.goods_transport.services.fleet_odometer.validate_vehicle_log_on_cancel",
	},
	"Sales Invoice": {
		"before_submit": "goods_transport.goods_transport.services.billing.validate_invoice_bilty_delivery",
	},
	"Trip Settlement": {
		"validate": "goods_transport.goods_transport.services.settlement.attach_driver_pay",
		"on_submit": "goods_transport.goods_transport.services.earnings.on_trip_settlement_submit",
	},
	"Transport Trip": {
		"on_cancel": "goods_transport.goods_transport.services.earnings.on_trip_cancel",
	},
	"User": {
		# Auto-hide non-transport modules the moment the Transport User role
		# is assigned via the desk. Guarded to only run once per user and
		# never for admins — see auto_block_non_transport_modules for rules.
		"validate": "goods_transport.setup.install_transport_user.auto_block_non_transport_modules",
	},
}

fixtures = [
	{
		"doctype": "Custom Field",
		"filters": [
			[
				"name",
				"in",
				[
					"Vehicle-transport_section",
					"Vehicle-ownership_type",
					"Vehicle-vehicle_type",
					"Vehicle-current_status",
					"Vehicle-transport_col_break",
					"Vehicle-transporter",
					"Vehicle-vehicle_owner",
					"Vehicle-default_driver",
					"Vehicle-capacity_section",
					"Vehicle-payload_capacity",
					"Vehicle-capacity_col_break",
					"Vehicle-volume_capacity",
					"Sales Invoice-transport_section",
					"Sales Invoice-bilty_references",
				],
			]
		],
	},
]

# Apps
# ------------------

# required_apps = []

add_to_apps_screen = [
	{
		"name": app_name,
		"logo": "/assets/goods_transport/images/goods-transport-logo.svg",
		"title": app_title,
		"route": "/desk/goods-transport",
	}
]

# Reuse submitted ERPNext vouchers as maintenance cost sources.
for voucher_type in ("Asset Repair", "Purchase Invoice", "Stock Entry", "Payment Entry", "Journal Entry"):
	doc_events.setdefault(voucher_type, {}).update({
		"validate": "goods_transport.goods_transport.services.fleet_costs.validate_repair_voucher",
	})

doc_events["Serial and Batch Bundle"] = {
	"before_submit": "goods_transport.goods_transport.services.fleet_tyres.protect_managed_stock",
	"before_cancel": "goods_transport.goods_transport.services.fleet_tyres.protect_managed_stock",
}

doc_events["Stock Entry"]["before_cancel"] = (
	"goods_transport.goods_transport.services.fleet_tyres.prevent_stock_cancellation"
)

# Includes in <head>
# ------------------

# include js, css files in header of desk.html
# Shared bench asset. The Desk theme is also used on sites without konektag_360 installed.
app_include_css = ["/assets/konektag_360/css/konektag_theme.css"]
# app_include_js = "/assets/goods_transport/js/goods_transport.js"

# include js, css files in header of web template
# web_include_css = "/assets/goods_transport/css/goods_transport.css"
# web_include_js = "/assets/goods_transport/js/goods_transport.js"

# include custom scss in every website theme (without file extension ".scss")
# website_theme_scss = "goods_transport/public/scss/website"

# include js, css files in header of web form
# webform_include_js = {"doctype": "public/js/doctype.js"}
# webform_include_css = {"doctype": "public/css/doctype.css"}

# include js in page
# page_js = {"page" : "public/js/file.js"}

# include js in doctype views
# doctype_js = {"doctype" : "public/js/doctype.js"}
# doctype_list_js = {"doctype" : "public/js/doctype_list.js"}
# doctype_tree_js = {"doctype" : "public/js/doctype_tree.js"}
# doctype_calendar_js = {"doctype" : "public/js/doctype_calendar.js"}

# Svg Icons
# ------------------
# include app icons in desk
# app_include_icons = "goods_transport/public/icons.svg"

# Home Pages
# ----------

# application home page (will override Website Settings)
# home_page = "login"

# website user home page (by Role)
# role_home_page = {
# 	"Role": "home_page"
# }

# Generators
# ----------

# automatically create page for each record of this doctype
# website_generators = ["Web Page"]

# Jinja
# ----------

# add methods and filters to jinja environment
# jinja = {
# 	"methods": "goods_transport.utils.jinja_methods",
# 	"filters": "goods_transport.utils.jinja_filters"
# }

# Installation
# ------------

# before_install = "goods_transport.install.before_install"
# after_install = "goods_transport.install.after_install"

# Uninstallation
# ------------

# before_uninstall = "goods_transport.uninstall.before_uninstall"
# after_uninstall = "goods_transport.uninstall.after_uninstall"

# Integration Setup
# ------------------
# To set up dependencies/integrations with other apps
# Name of the app being installed is passed as an argument

# before_app_install = "goods_transport.utils.before_app_install"
# after_app_install = "goods_transport.utils.after_app_install"

# Integration Cleanup
# -------------------
# To clean up dependencies/integrations with other apps
# Name of the app being uninstalled is passed as an argument

# before_app_uninstall = "goods_transport.utils.before_app_uninstall"
# after_app_uninstall = "goods_transport.utils.after_app_uninstall"

# Desk Notifications
# ------------------
# See frappe.core.notifications.get_notification_config

# notification_config = "goods_transport.notifications.get_notification_config"

# Permissions
# -----------
# Permissions evaluated in scripted ways

# permission_query_conditions = {
# 	"Event": "frappe.desk.doctype.event.event.get_permission_query_conditions",
# }
#
# has_permission = {
# 	"Event": "frappe.desk.doctype.event.event.has_permission",
# }

# DocType Class
# ---------------
# Override standard doctype classes

# override_doctype_class = {
# 	"ToDo": "custom_app.overrides.CustomToDo"
# }

# Document Events
# ---------------
# Hook on document methods and events

# doc_events = {
# 	"*": {
# 		"on_update": "method",
# 		"on_cancel": "method",
# 		"on_trash": "method"
# 	}
# }

# Scheduled Tasks
# ---------------

# scheduler_events = {
# 	"all": [
# 		"goods_transport.tasks.all"
# 	],
# 	"daily": [
# 		"goods_transport.tasks.daily"
# 	],
# 	"hourly": [
# 		"goods_transport.tasks.hourly"
# 	],
# 	"weekly": [
# 		"goods_transport.tasks.weekly"
# 	],
# 	"monthly": [
# 		"goods_transport.tasks.monthly"
# 	],
# }

# Testing
# -------

# before_tests = "goods_transport.install.before_tests"

# Overriding Methods
# ------------------------------
#
# override_whitelisted_methods = {
# 	"frappe.desk.doctype.event.event.get_events": "goods_transport.event.get_events"
# }
#
# each overriding function accepts a `data` argument;
# generated from the base implementation of the doctype dashboard,
# along with any modifications made in other Frappe apps
# override_doctype_dashboards = {
# 	"Task": "goods_transport.task.get_dashboard_data"
# }

# exempt linked doctypes from being automatically cancelled
#
# auto_cancel_exempted_doctypes = ["Auto Repeat"]

# Ignore links to specified DocTypes when deleting documents
# -----------------------------------------------------------

# ignore_links_on_delete = ["Communication", "ToDo"]

# Request Events
# ----------------
# before_request = ["goods_transport.utils.before_request"]
# after_request = ["goods_transport.utils.after_request"]

# Job Events
# ----------
# before_job = ["goods_transport.utils.before_job"]
# after_job = ["goods_transport.utils.after_job"]

# User Data Protection
# --------------------

# user_data_fields = [
# 	{
# 		"doctype": "{doctype_1}",
# 		"filter_by": "{filter_by}",
# 		"redact_fields": ["{field_1}", "{field_2}"],
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_2}",
# 		"filter_by": "{filter_by}",
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_3}",
# 		"strict": False,
# 	},
# 	{
# 		"doctype": "{doctype_4}"
# 	}
# ]

# Authentication and authorization
# --------------------------------

# auth_hooks = [
# 	"goods_transport.auth.validate"
# ]

# Automatically update python controller files with type annotations for this app.
# export_python_type_annotations = True

# default_log_clearing_doctypes = {
# 	"Logging DocType Name": 30  # days to retain logs
# }

# Translation
# ------------
# List of apps whose translatable strings should be excluded from this app's translations.
# ignore_translatable_strings_from = []


scheduler_events = {
	"daily": [
		"goods_transport.goods_transport.doctype.vehicle_maintenance_schedule.vehicle_maintenance_schedule.refresh_daily_alerts",
	],
	"cron": {
		"*/5 * * * *": ["goods_transport.goods_transport.services.fuel.expire"],
	},
}
