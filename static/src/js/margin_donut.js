/**
 * Anneau de répartition d'un mois de facturation d'un calcul de marge : ce qui revient au consultant (net,
 * puis charges), les frais fixes et indirects, les autres coûts et la marge de la société.
 *
 * Dessiné en SVG, sans bibliothèque : chaque part est un arc du cercle.
 */
import { Component } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/l10n/translation";
import { standardFieldProps } from "@web/views/fields/standard_field_props";

const COLORS = {
    net: "#1f8a70",
    allowances: "#7cc6a4",
    employee: "#e3a72f",
    employer: "#d9822b",
    pay: "#e3a72f",
    overhead: "#8794a8",
    other: "#c0c4cf",
    margin: "#714b67",
};

export class MarginDonutField extends Component {
    static template = "mission_report.MarginDonutField";
    static props = { ...standardFieldProps };

    get data() {
        return this.props.record.data[this.props.name] || { segments: [], total: 0, deficit: 0 };
    }

    money(amount) {
        const number = Math.round(amount).toLocaleString((document.documentElement.lang || "fr").replace("_", "-"));
        const symbol = this.data.symbol || "";
        return this.data.after ? `${number} ${symbol}` : `${symbol} ${number}`;
    }

    /** The arcs: each part of the ring, in percent of the circle (100 long), after the previous ones. */
    get arcs() {
        const segments = this.data.segments || [];
        const sum = segments.reduce((total, part) => total + part.value, 0);
        let done = 0;
        return segments.map((part) => {
            const share = sum ? (part.value / sum) * 100 : 0;
            const arc = {
                ...part,
                share,
                color: COLORS[part.key] || "#999",
                dash: `${Math.max(share - 0.4, 0)} ${100 - Math.max(share - 0.4, 0)}`,
                offset: 25 - done,
            };
            done += share;
            return arc;
        });
    }

    get deficitLabel() {
        return `${_t("The costs exceed the billing by")} ${this.money(this.data.deficit)} ${_t("a month")}`;
    }
}

export const marginDonutField = {
    component: MarginDonutField,
    displayName: "Breakdown of the billing",
    supportedTypes: ["json"],
};

registry.category("fields").add("margin_donut", marginDonutField);
