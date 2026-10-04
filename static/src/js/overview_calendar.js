/**
 * Vue d'ensemble : navigation et saisie depuis le calendrier.
 *
 * - Cliquer sur une saisie ouvre la fenêtre d'Odoo (ruban d'état, approuver, refuser), sans quitter le calendrier.
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
import { useBus } from "@web/core/utils/hooks";
import { patch } from "@web/core/utils/patch";

import { missionBus } from "./leave_edit_action";
import { TimeOffReportCalendarController } from "@hr_holidays/views/calendar/calendar_controller";
import { TimeOffCalendarModel } from "@hr_holidays/views/calendar/calendar_model";
import { TimeOffCalendarYearRenderer } from "@hr_holidays/views/calendar/year/calendar_year_renderer";
import { TimeOffFormViewDialog } from "@hr_holidays/views/view_dialog/form_view_dialog";

const HOVER_DELAY = 120;
const LEAVE_DELAY = 300;
// Passer d'un jour à son voisin, bulle ouverte : un peu plus de patience, pour ne pas alterner
// entre deux bulles quand la souris longe la limite des cases.
const SWITCH_DELAY = 250;
// Bande, au bord de chaque case, où la souris ne survole aucun jour.
const CELL_EDGE = 3;

patch(TimeOffReportCalendarController.prototype, {
    setup() {
        super.setup(...arguments);
        // « Modifier » : la fiche s'ouvre à part, le calendrier se relit quand elle se ferme.
        useBus(missionBus, "reload", () => this.model.load());
    },

    /**
     * Clic sur une saisie : la fenêtre d'Odoo (ruban d'état, approuver, refuser). À sa fermeture,
     * le calendrier est relu : une approbation par ses boutons ne déclenche pas de rechargement.
     */
    async editRecord() {
        await super.editRecord(...arguments);
        await this.model.load();
        this.env.timeOffBus?.trigger("update_dashboard");
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
     * Un lien peut demander une échelle (contexte mission_scale) : elle vaut pour cette
     * ouverture. Le modèle mémorise l'échelle de chaque navigation ; une fois imposée,
     * il l'écrit sous une autre clé, pour ne pas remplacer celle de la personne.
     */
    get storageKey() {
        return this._missionScaleApplied ? `${super.storageKey}-mission` : super.storageKey;
    },

    async load(params = {}) {
        const scale = params.context && params.context.mission_scale;
        if (scale && !this._missionScaleApplied) {
            this._missionScaleApplied = true;
            return super.load({ ...params, scale });
        }
        return super.load(params);
    },
});

patch(TimeOffCalendarYearRenderer.prototype, {
    setup() {
        super.setup();
        this.hoverTimer = null;
        this.leaveTimer = null;
        onMounted(() => {
            const root = this.rootRef.el;
            root.addEventListener("click", (ev) => this.onYearClick(ev));
            root.addEventListener("mousemove", (ev) => this.onYearMove(ev));
            root.addEventListener("mouseleave", () => {
                this.hoverCell = null;
                this.scheduleClose();
            });
        });
        onWillUnmount(() => {
            browser.clearTimeout(this.hoverTimer);
            browser.clearTimeout(this.leaveTimer);
        });
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

    /**
     * Survol : la case sous la souris est calculée sur la position du pointeur. Les saisies
     * multi-jours sont dessinées par FullCalendar dans la case de leur premier jour, si bien que
     * l'entrée de cette case se déclenchait aussi sur ses voisines, et sur la limite entre deux
     * cases : une bulle décalée apparaissait là où rien n'est survolable. Une bande de
     * quelques pixels au bord de chaque case ne compte pas.
     */
    onYearMove(ev) {
        if (this.env.isSmall) {
            return;
        }
        const cell = this.dayCellAt(ev.clientX, ev.clientY);
        if (cell === this.hoverCell) {
            return;
        }
        this.hoverCell = cell;
        browser.clearTimeout(this.leaveTimer);
        browser.clearTimeout(this.hoverTimer);
        if (!cell) {
            this.scheduleClose();
            return;
        }
        // La bulle de ce jour est déjà ouverte : on la garde, sans la fermer ni la rouvrir.
        if (this.shownEl === cell && document.querySelector(".o_cw_popover_holidays")) {
            return;
        }
        this.hoverTimer = browser.setTimeout(
            () => this.showDayPopover(cell),
            this.shownEl ? SWITCH_DELAY : HOVER_DELAY
        );
    },

    dayCellAt(x, y) {
        const month = document.elementFromPoint(x, y)?.closest(".fc-month-container");
        if (!month) {
            return null;
        }
        const cells = month.querySelectorAll(".fc-daygrid-day[data-date]:not(.fc-day-other)");
        for (const cell of cells) {
            const box = cell.getBoundingClientRect();
            if (
                x >= box.left + CELL_EDGE &&
                x <= box.right - CELL_EDGE &&
                y >= box.top + CELL_EDGE &&
                y <= box.bottom - CELL_EDGE
            ) {
                return cell;
            }
        }
        return null;
    },

    closeDayPopovers() {
        this.shownEl = null;
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
        this.shownEl = el;
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
