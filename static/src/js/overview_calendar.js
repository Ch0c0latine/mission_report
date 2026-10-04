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
import { onMounted, onWillStart, onWillUnmount, onWillUpdateProps } from "@odoo/owl";
import { browser } from "@web/core/browser/browser";
import { serializeDate } from "@web/core/l10n/dates";
import { useBus } from "@web/core/utils/hooks";
import { patch } from "@web/core/utils/patch";

import { missionBus } from "./leave_edit_action";
import { TimeOffCalendarCommonRenderer } from "@hr_holidays/views/calendar/common/calendar_common_renderer";
import { TimeOffReportCalendarController } from "@hr_holidays/views/calendar/calendar_controller";
import { TimeOffCalendarModel } from "@hr_holidays/views/calendar/calendar_model";
import { TimeOffCalendarYearRenderer } from "@hr_holidays/views/calendar/year/calendar_year_renderer";
import { TimeOffFormViewDialog } from "@hr_holidays/views/view_dialog/form_view_dialog";

const HOVER_DELAY = 120;
const LEAVE_DELAY = 300;
// Passer d'un jour à son voisin, bulle ouverte : un peu plus de patience, pour ne pas alterner
// entre deux bulles quand la souris longe la limite des cases.
const SWITCH_DELAY = 250;
// Journée représentée par une case : les barres d'une demi-journée ou d'heures s'y placent
// selon l'heure (matin = de la gauche jusqu'au milieu, fin d'après-midi = à droite).
const DAY_START = 8;
const DAY_END = 17;
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
        // Jours fériés de l'année affichée : repérés sur la grille, avec leur nom au survol.
        this.holidayByDay = new Map();
        onWillStart(() => this.loadHolidays(this.props));
        onWillUpdateProps((props) => this.loadHolidays(props));
        onMounted(() => {
            const root = this.rootRef.el;
            root.addEventListener("click", (ev) => this.onYearClick(ev));
            root.addEventListener("mousemove", (ev) => this.onYearMove(ev));
            root.addEventListener("mouseleave", () => {
                this.hoverCell = null;
                this.scheduleClose();
            });
            // La bulle (hors du calendrier, ajoutée à la page) reste ouverte tant que la souris y est,
            // pour que ses saisies se cliquent ; elle se ferme à sa sortie.
            document.addEventListener("mouseover", this.onBubbleOver);
            document.addEventListener("mouseout", this.onBubbleOut);
        });
        this.onBubbleOver = (ev) => {
            if (ev.target.closest?.(".o_cw_popover_holidays")) {
                browser.clearTimeout(this.leaveTimer);
                browser.clearTimeout(this.hoverTimer);
            }
        };
        this.onBubbleOut = (ev) => {
            const leaving = ev.target.closest?.(".o_cw_popover_holidays");
            if (leaving && !ev.relatedTarget?.closest?.(".o_cw_popover_holidays")) {
                this.scheduleClose();
            }
        };
        onWillUnmount(() => {
            browser.clearTimeout(this.hoverTimer);
            browser.clearTimeout(this.leaveTimer);
            document.removeEventListener("mouseover", this.onBubbleOver);
            document.removeEventListener("mouseout", this.onBubbleOut);
        });
    },

    get options() {
        return { ...super.options, dayCellDidMount: (info) => this.markHoliday(info) };
    },

    async loadHolidays(props) {
        const { rangeStart, rangeEnd, employeeId } = props.model;
        const holidays = await this.orm.call(
            "hr.employee",
            "get_public_holidays_data",
            [serializeDate(rangeStart, "datetime"), serializeDate(rangeEnd, "datetime")],
            { context: { employee_id: employeeId } }
        );
        this.holidayByDay = new Map();
        for (const holiday of holidays) {
            const last = luxon.DateTime.fromISO(holiday.end).minus({ milliseconds: 1 });
            let day = luxon.DateTime.fromISO(holiday.start).startOf("day");
            while (day <= last) {
                this.holidayByDay.set(day.toISODate(), holiday.title);
                day = day.plus({ days: 1 });
            }
        }
    },

    /** Un jour férié : case teintée et nom en infobulle (le grisé seul ne le distinguait pas d'un week-end). */
    markHoliday({ el }) {
        const title = this.holidayByDay.get(el.dataset.date);
        if (title) {
            el.classList.add("o_mission_holiday");
            el.title = title;
        }
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

patch(TimeOffCalendarCommonRenderer.prototype, {
    get options() {
        return { ...super.options, eventOrder: (a, b) => this.missionEventOrder(a, b) };
    },

    /**
     * Vue mensuelle : une saisie d'un seul jour (demi-journée, heures) s'affichait en pastille,
     * à part des autres. Elle devient une barre, comme les saisies de plusieurs jours.
     */
    eventClassNames(info) {
        const classes = super.eventClassNames(info);
        if (!classes.includes("o_event_dot")) {
            return classes;
        }
        return classes.filter((name) => name !== "o_event_dot").concat("o_mission_timebar");
    },

    /** Les barres d'une même personne se suivent (début, puis nom), pour se partager une ligne. */
    missionEventOrder(a, b) {
        const records = this.props.model.records;
        const ra = records[a.id];
        const rb = records[b.id];
        const bars = ra && rb && ra.isMonth && !ra.isAllDay && !ra.isTimeHidden && !rb.isAllDay && !rb.isTimeHidden;
        if (bars) {
            const name = (r) => (r.rawRecord?.employee_id?.[1] || "").toString();
            return name(ra).localeCompare(name(rb)) || ra.start.toMillis() - rb.start.toMillis();
        }
        // Le reste, dans l'ordre habituel de FullCalendar : début, durée décroissante, titre.
        const start = a.start - b.start;
        const duration = (b.end - b.start) - (a.end - a.start);
        return start || duration || String(a.title).localeCompare(String(b.title));
    },

    onEventDidMount({ el, event }) {
        super.onEventDidMount(...arguments);
        const record = this.props.model.records[event.id];
        if (!record || !el.classList.contains("o_mission_timebar")) {
            return;
        }
        const hour = (date) => date.hour + date.minute / 60;
        const span = DAY_END - DAY_START;
        const left = Math.min(Math.max((hour(record.start) - DAY_START) / span, 0), 0.94);
        const right = Math.min(Math.max((hour(record.end) - DAY_START) / span, left + 0.06), 1);
        el.style.marginLeft = `${(left * 100).toFixed(1)}%`;
        el.style.width = `${((right - left) * 100).toFixed(1)}%`;
        el.dataset.missionEmployee = record.rawRecord?.employee_id?.[0] || "";
        el.querySelector(".fc-time")?.remove();
        browser.setTimeout(() => this.shareDayRows(el), 0);
    },

    /** Deux barres de la même personne le même jour : sur une seule ligne. */
    shareDayRows(el) {
        const container = el.closest(".fc-daygrid-day-events");
        if (!container) {
            return;
        }
        let previous = null;
        for (const harness of container.querySelectorAll(":scope > .fc-daygrid-event-harness")) {
            const bar = harness.querySelector(".o_mission_timebar");
            harness.classList.toggle(
                "o_mission_samerow",
                Boolean(bar) && bar.dataset.missionEmployee === previous
            );
            previous = bar ? bar.dataset.missionEmployee : null;
        }
    },
});
