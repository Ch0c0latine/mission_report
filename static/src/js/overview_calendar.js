/**
 * Vue d'ensemble : navigation et saisie depuis le calendrier.
 *
 * - Cliquer sur une saisie ouvre sa fiche (Management > Saisies), pas une popup.
 * - Cliquer sur un jour, ou glisser sur une plage, crée une saisie.
 * - Vue annuelle : la liste des saisies d'un jour s'affiche au survol ; le titre
 *   d'un mois mène à la vue mensuelle de ce mois.
 * - Un lien peut ouvrir un calendrier sur un mois (contexte mission_scale)
 *   sans changer l'échelle habituelle de la personne.
 *
 * Les écrans viennent d'hr_holidays (calendrier de l'onglet « Vue d'ensemble »,
 * js_class time_off_report_calendar) : on les complète par patch.
 */
import { onMounted, onWillUnmount } from "@odoo/owl";
import { browser } from "@web/core/browser/browser";
import { serializeDate } from "@web/core/l10n/dates";
import { user } from "@web/core/user";
import { patch } from "@web/core/utils/patch";

import { TimeOffReportCalendarController } from "@hr_holidays/views/calendar/calendar_controller";
import { TimeOffCalendarModel } from "@hr_holidays/views/calendar/calendar_model";
import { TimeOffCalendarYearRenderer } from "@hr_holidays/views/calendar/year/calendar_year_renderer";
import { TimeOffFormViewDialog } from "@hr_holidays/views/view_dialog/form_view_dialog";

const APPROVAL_ACTION = "hr_holidays.hr_leave_action_action_approve_department";
const HOVER_DELAY = 120;
const LEAVE_DELAY = 300;

patch(TimeOffReportCalendarController.prototype, {
    /** Clic sur une saisie : sa fiche (les employés ne lisent que les leurs : ils gardent la bulle). */
    async editRecord(record) {
        if (!record.id) {
            return;
        }
        if (!(await user.hasGroup("hr_holidays.group_hr_holidays_user"))) {
            return super.editRecord(...arguments);
        }
        await this.action.doAction(APPROVAL_ACTION, {
            props: { resId: record.id },
            viewType: "form",
        });
    },

    /** Clic sur un jour ou une plage : nouvelle saisie. */
    createRecord(record) {
        const start = record.start;
        const end = record.end || record.start;
        const context = {
            form_view_ref: "hr_holidays.hr_leave_view_form",
            default_request_date_from: serializeDate(start),
            default_request_date_to: serializeDate(end),
        };
        return new Promise((resolve) => {
            this.displayDialog(
                TimeOffFormViewDialog,
                {
                    resModel: "hr.leave",
                    title: "Nouvelle saisie",
                    context,
                    size: "md",
                    onRecordSaved: () => this.model.load(),
                    onRecordDeleted: () => {},
                    onLeaveCancelled: () => {},
                },
                { onClose: () => resolve() }
            );
        });
    },

    newTimeOffRequest() {
        return this.createRecord({ start: luxon.DateTime.local() });
    },
});

patch(TimeOffCalendarModel.prototype, {
    /**
     * Un lien peut demander une échelle (contexte mission_scale) : appliquée à
     * l'ouverture seulement, et sans remplacer l'échelle mémorisée.
     */
    async load(params = {}) {
        const scale = params.context && params.context.mission_scale;
        if (scale && !this._missionScaleApplied) {
            this._missionScaleApplied = true;
            const remembered = this.getLocalStorageScale();
            await super.load({ ...params, scale });
            browser.localStorage.setItem(this.storageKey, remembered);
            return;
        }
        return super.load(params);
    },
});

patch(TimeOffCalendarYearRenderer.prototype, {
    setup() {
        super.setup();
        this.hoverTimer = null;
        this.leaveTimer = null;
        onMounted(() => this.rootRef.el.addEventListener("click", (ev) => this.onYearClick(ev)));
        onWillUnmount(() => {
            browser.clearTimeout(this.hoverTimer);
            browser.clearTimeout(this.leaveTimer);
        });
    },

    get options() {
        return { ...super.options, dayCellDidMount: this.onDayCellMount };
    },

    /** Un clic sur un jour crée une saisie ; la liste de la journée vient au survol. */
    async onDateClick(info) {
        if (this.env.isSmall) {
            return super.onDateClick(info);
        }
        browser.clearTimeout(this.hoverTimer);
        this.closeDayPopovers();
        if (this.props.model.canCreate) {
            this.props.createRecord({
                start: luxon.DateTime.fromISO(info.dateStr),
                isAllDay: true,
            });
        }
    },

    onDayCellMount({ el }) {
        if (this.env.isSmall) {
            return;
        }
        el.addEventListener("mouseenter", () => {
            browser.clearTimeout(this.leaveTimer);
            browser.clearTimeout(this.hoverTimer);
            this.hoverTimer = browser.setTimeout(() => this.showDayPopover(el), HOVER_DELAY);
        });
        el.addEventListener("mouseleave", () => this.scheduleClose());
    },

    closeDayPopovers() {
        this.popover.close();
        this.mandatoryDayPopover.close();
    },

    scheduleClose() {
        browser.clearTimeout(this.hoverTimer);
        browser.clearTimeout(this.leaveTimer);
        this.leaveTimer = browser.setTimeout(() => this.closeDayPopovers(), LEAVE_DELAY);
    },

    /** La bulle reste ouverte tant que la souris est dessus. */
    keepPopoverWhileHovered() {
        browser.setTimeout(() => {
            const bubble = document.querySelector(".o_cw_popover_holidays");
            if (!bubble || bubble.dataset.missionHover) {
                return;
            }
            bubble.dataset.missionHover = "1";
            bubble.addEventListener("mouseenter", () => browser.clearTimeout(this.leaveTimer));
            bubble.addEventListener("mouseleave", () => this.scheduleClose());
        }, 0);
    },

    async showDayPopover(el) {
        const dateStr = el.dataset.date;
        if (!dateStr) {
            return;
        }
        const date = luxon.DateTime.fromISO(dateStr);
        const records = Object.values(this.props.model.records).filter((r) =>
            luxon.Interval.fromDateTimes(r.start.startOf("day"), r.end.endOf("day")).contains(date)
        );
        const isMandatory = [...el.classList].some((name) => name.startsWith("hr_mandatory_day_"));
        if (!records.length && !isMandatory) {
            return;
        }
        this.closeDayPopovers();
        const props = this.getPopoverProps(date, records);
        if (isMandatory) {
            const data = await this.orm.call("hr.employee", "get_mandatory_days_data", [date, date]);
            data.forEach((day) => {
                day.start = luxon.DateTime.fromISO(day.start);
                day.end = luxon.DateTime.fromISO(day.end);
            });
            props.records = data.concat(props.records);
            this.mandatoryDayPopover.open(el, props, "o_cw_popover_holidays o_cw_popover");
        } else {
            this.openPopover(el, date, records);
        }
        this.keepPopoverWhileHovered();
    },

    /**
     * Le titre d'un mois mène à la vue mensuelle de ce mois. FullCalendar refait
     * son en-tête à chaque rendu : le clic est capté sur l'ensemble de la vue.
     */
    onYearClick(ev) {
        const title = ev.target.closest(".fc-toolbar-title");
        const first = title
            ?.closest(".fc-month-container")
            ?.querySelector(".fc-daygrid-day[data-date]:not(.fc-day-other)");
        if (!first) {
            return;
        }
        this.closeDayPopovers();
        this.props.model.load({ date: luxon.DateTime.fromISO(first.dataset.date), scale: "month" });
    },
});
